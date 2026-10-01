import SwiftUI
import AppKit
import UniformTypeIdentifiers

struct TTSShortcutsView: View {
    @Binding var phrases: TTSPhrases
    var soundNames: [String] = []
    @State private var editing: String?
    @State private var shortcut = ""
    @State private var phrase = ""
    @State private var error: String?

    private func clearEditor() { editing = nil; shortcut = ""; phrase = ""; error = nil }

    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            Text(L10n.text("입력창에 단축어를 입력하고 Enter를 누르면 저장한 문장을 읽습니다.")).font(.callout).foregroundStyle(.secondary)
            FormSection {
                VStack(alignment: .leading, spacing: 6) {
                    Text(L10n.text("단축어"))
                    TextField(L10n.text("예: ㅎㅇ"), text: $shortcut).textFieldStyle(.roundedBorder).accessibilityLabel(L10n.text("단축어"))
                    Text(L10n.text("읽을 문장")).padding(.top, 6)
                    TextField(L10n.text("예: 안녕하세요, 반갑습니다!"), text: $phrase, axis: .vertical)
                        .lineLimit(3...5).textFieldStyle(.roundedBorder).accessibilityLabel(L10n.text("읽을 문장"))
                }.padding(.vertical, 10)
                HStack {
                    if let error { Text(L10n.message(error)).font(.caption).foregroundStyle(.red) }
                    Spacer()
                    if editing != nil { Button(L10n.text("취소"), action: clearEditor) }
                    Button(L10n.text(editing == nil ? "추가" : "저장")) {
                        do {
                            try phrases.save(shortcut: shortcut, phrase: phrase, replacing: editing, soundNames: soundNames)
                            clearEditor()
                        } catch { self.error = error.localizedDescription }
                    }.buttonStyle(.borderedProminent)
                }.padding(.vertical, 8)
            }
            FormSection {
                if phrases.entries.isEmpty { Text(L10n.text("저장된 단축어 없음")).foregroundStyle(.secondary) }
                ForEach(phrases.entries.keys.sorted(), id: \.self) { key in
                    HStack(alignment: .center, spacing: 12) {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(key).font(.system(size: 13, weight: .semibold)).lineLimit(2)
                            Text(phrases.entries[key] ?? "").font(.callout).foregroundStyle(.secondary).lineLimit(3)
                        }.frame(maxWidth: .infinity, alignment: .leading)
                        IconButton(symbol: "pencil", title: L10n.text("수정")) { editing = key; shortcut = key; phrase = phrases.entries[key] ?? ""; error = nil }
                        IconButton(symbol: "trash", title: L10n.text("삭제"), destructive: true) {
                            phrases.remove(key)
                            if editing == key { clearEditor() }
                        }
                    }.padding(.vertical, 10)
                        .background(editing == key ? Theme.accent.opacity(0.06) : .clear)
                }
            }
        }
    }
}

struct VoiceLibraryView: View {
    @ObservedObject var state: AppState
    @State private var editingID: UUID?
    @State private var recordingPage = false
    @State private var voiceToDelete: VoiceProfile?
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            if recordingPage {
                BackButton { editingID = state.cancelVoiceRecording(); recordingPage = false }
                FormSection {
                    TextField(L10n.text("대본 (선택)"), text: $state.voiceRecordingTranscript, axis: .vertical)
                        .lineLimit(4...7).textFieldStyle(.roundedBorder).disabled(state.voiceTranscribing).padding(.vertical, 12)
                    HStack(spacing: 8) {
                        if state.voiceRecordingActive {
                            Circle().fill(.red).frame(width: 8, height: 8)
                            Text(L10n.text("녹음 중 · {0} / 30초", String(format: "%.1f", state.voiceRecordingSeconds))).monospacedDigit()
                        } else if state.voiceTranscribing { ProgressView().controlSize(.small); Text(L10n.text("받아쓰는 중…")) }
                        else if state.voiceRecordingPending { ProgressView().controlSize(.small); Text(L10n.text("마이크 준비 중…")) }
                        Spacer()
                        if state.voiceRecordingBusy {
                            Button(L10n.text("취소")) { editingID = state.cancelVoiceRecording(); recordingPage = false }
                            if !state.voiceTranscribing {
                                Button(L10n.text("완료")) { state.finishVoiceRecording() }.buttonStyle(.borderedProminent)
                                    .disabled(!state.voiceRecordingActive || state.voiceRecordingSeconds < 3)
                            }
                        } else {
                            Button { state.startVoiceRecording { editingID = $0; recordingPage = false } } label: {
                                Label(L10n.text("녹음 시작"), systemImage: "record.circle")
                            }.buttonStyle(.borderedProminent).tint(.red)
                        }
                    }.padding(.vertical, 10)
                }
            } else if let id = editingID, let index = state.clonedVoices.firstIndex(where: { $0.id == id }) {
                BackButton { editingID = nil }
                FormSection {
                    FormRow(L10n.text("목소리명")) {
                        TextField(L10n.text("목소리명"), text: $state.clonedVoices[index].name).textFieldStyle(.roundedBorder).frame(width: 240).disabled(state.voiceTranscribing)
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        Text(L10n.text("대본"))
                        TextField(L10n.text("음성의 대본"), text: $state.clonedVoices[index].transcript, axis: .vertical)
                            .lineLimit(4...7).textFieldStyle(.roundedBorder).disabled(state.voiceTranscribing)
                    }.padding(.vertical, 10)
                    HStack(spacing: 8) {
                        if state.voiceTranscribing {
                            ProgressView().controlSize(.small)
                            Text(L10n.text("받아쓰는 중…")).font(.caption)
                            Button(L10n.text("취소")) { state.cancelVoiceRecording() }
                        } else {
                            Button(L10n.text("대본 자동 입력")) { state.transcribeVoice(id) }.disabled(state.modelWorkIsBusy)
                            StatusBadge(text: L10n.text(state.clonedVoices[index].ready ? "등록 완료" : "이름·대본 필요"), ok: state.clonedVoices[index].ready)
                        }
                        Spacer()
                        IconButton(symbol: "trash", title: L10n.text("삭제"), destructive: true) { voiceToDelete = state.clonedVoices[index] }.disabled(state.voiceTranscribing)
                    }.padding(.vertical, 8)
                }
            } else {
                AudioAddForm(types: [.wav, .aiff, .mp3, .mpeg4Audio], placeholder: L10n.text("목소리명")) { files, name in
                    editingID = state.addClonedVoices(files, name: name)
                } extra: {
                    Button { state.voiceRecordingTranscript = ""; recordingPage = true } label: { Label(L10n.text("마이크 녹음"), systemImage: "mic") }
                }.disabled(state.modelWorkIsBusy)
                Text(L10n.text("3~30초 길이의 깨끗한 음성을 사용하세요. 대본은 자동으로 입력합니다.")).font(.caption).foregroundStyle(.secondary)
                FormSection {
                    if state.clonedVoices.isEmpty { Text(L10n.text("저장된 목소리 없음")).foregroundStyle(.secondary) }
                    ForEach(state.clonedVoices) { voice in
                        Button { editingID = voice.id } label: {
                            HStack(spacing: 10) {
                                Image(systemName: "person.wave.2").foregroundStyle(Theme.accent).frame(width: 20)
                                Text(voice.name.isEmpty ? voice.sourceName : voice.name)
                                Spacer()
                                if !voice.ready { StatusBadge(text: L10n.text("대본 필요"), ok: false) }
                                Image(systemName: "chevron.right").font(.system(size: 11, weight: .semibold)).foregroundStyle(.tertiary)
                            }.padding(.vertical, 12).contentShape(Rectangle())
                        }.buttonStyle(.plain)
                    }
                }
            }
        }.disabled(state.speaking)
            .alert(L10n.text("목소리를 삭제할까요?"), isPresented: Binding(get: { voiceToDelete != nil }, set: { if !$0 { voiceToDelete = nil } }), presenting: voiceToDelete) { voice in
                Button(L10n.text("삭제"), role: .destructive) { state.deleteClonedVoice(voice.id); editingID = nil; voiceToDelete = nil }
                Button(L10n.text("취소"), role: .cancel) { voiceToDelete = nil }
            } message: { voice in Text(L10n.text("{0} 목소리를 휴지통으로 이동합니다.", voice.name)) }
            .onDisappear { state.cancelVoiceRecording() }
            .onReceive(NotificationCenter.default.publisher(for: NSWindow.willCloseNotification)) { notification in
                if (notification.object as? NSWindow)?.title == "STTS" { state.cancelVoiceRecording() }
            }
    }
}

struct ToolDrawer: View {
    @ObservedObject var state: AppState
    let tool: String
    let close: () -> Void
    private var title: String { AppContract.shared.tools.first { $0.id == tool }?.title ?? "" }
    var body: some View {
        VStack(spacing: 0) {
            Capsule().fill(.tertiary).frame(width: 36, height: 4).padding(.top, 8)
            HStack {
                Text(L10n.text(title)).font(.system(size: 20, weight: .bold))
                Spacer()
                Button(action: close) {
                    Image(systemName: "xmark").font(.system(size: 11, weight: .bold)).foregroundStyle(.secondary)
                        .frame(width: 26, height: 26).background(.primary.opacity(0.07), in: Circle())
                }.buttonStyle(.plain).accessibilityLabel(L10n.text("닫기")).keyboardShortcut(.cancelAction)
            }.padding(.horizontal, 24).padding(.top, 10).padding(.bottom, 6)
            ScrollView {
                Group {
                    switch tool {
                    case "voice": VoiceLibraryView(state: state)
                    case "phrases": TTSShortcutsView(phrases: $state.ttsPhrases, soundNames: state.soundboard.clips.map(\.name))
                    default: SoundboardView(state: state, library: state.soundboard)
                    }
                }.frame(maxWidth: .infinity, alignment: .topLeading).padding(.horizontal, 24).padding(.vertical, 14)
            }.scrollIndicators(.never)
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.primary.opacity(0.03), in: UnevenRoundedRectangle(topLeadingRadius: 24, topTrailingRadius: 24))
            .background(Color(nsColor: .windowBackgroundColor), in: UnevenRoundedRectangle(topLeadingRadius: 24, topTrailingRadius: 24))
            .shadow(color: .black.opacity(0.14), radius: 20, y: -4)
    }
}

private struct BackButton: View {
    let action: () -> Void
    var body: some View {
        Button(action: action) { Label(L10n.text("목록"), systemImage: "chevron.left").font(.system(size: 13, weight: .medium)) }
            .buttonStyle(.borderless)
    }
}

private struct StatusBadge: View {
    let text: String
    let ok: Bool
    var body: some View {
        Text(text).font(.caption.weight(.medium)).foregroundStyle(ok ? Color.green : Color.orange)
            .padding(.horizontal, 7).padding(.vertical, 2)
            .background((ok ? Color.green : Color.orange).opacity(0.12), in: Capsule())
    }
}

struct IconButton: View {
    let symbol: String
    let title: String
    var destructive = false
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 12, weight: .medium)).frame(width: 26, height: 26).contentShape(Rectangle())
        }.buttonStyle(.borderless).foregroundStyle(destructive ? Color.red : .secondary).help(title).accessibilityLabel(title)
    }
}

private struct SoundboardView: View {
    @ObservedObject var state: AppState
    @ObservedObject var library: SoundboardLibrary
    @State private var deleting: SoundboardClip?
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            AudioAddForm(types: [.audio], placeholder: L10n.text("사운드 이름 (입력창에 입력하면 재생)"), add: importFiles) { EmptyView() }
                .disabled(state.speaking || state.voiceRecordingBusy || state.managingModels || library.loadError != nil)
            HStack {
                Text(L10n.text("사운드마다 단축키를 지정하면 게임 중에도 바로 재생합니다.")).font(.caption).foregroundStyle(.secondary)
                Spacer()
                if state.playingSoundID != nil { Button { state.cancelSpeech() } label: { Label(L10n.text("재생 중지"), systemImage: "stop.fill") } }
            }
            if let error = library.loadError { Text(L10n.message(error)).foregroundStyle(.red) }
            if library.clips.isEmpty && library.loadError == nil {
                VStack(spacing: 10) {
                    Image(systemName: "square.grid.2x2").font(.system(size: 26, weight: .light)).foregroundStyle(.tertiary)
                    Text(L10n.text("등록된 사운드 없음")).foregroundStyle(.secondary)
                }.frame(maxWidth: .infinity).padding(.vertical, 40)
            } else if !library.clips.isEmpty {
                FormSection {
                    ForEach(library.clips) { clip in
                        let playing = state.playingSoundID == clip.id
                        HStack(spacing: 12) {
                            Button {
                                if playing { state.cancelSpeech() }
                                else { state.playSound(clip, from: library.audioURL(clip)) }
                            } label: {
                                Image(systemName: playing ? "stop.fill" : "play.fill").font(.system(size: 11)).foregroundStyle(playing ? .white : Theme.accent)
                                    .frame(width: 30, height: 30).background(playing ? Theme.accent : Theme.accent.opacity(0.12), in: Circle())
                            }.buttonStyle(.plain)
                                .accessibilityLabel(playing ? L10n.text("재생 중지") : L10n.text("{0} 재생", clip.name))
                                .disabled(!state.ttsEnabled || state.voiceRecordingBusy || (state.speaking && !playing))
                            VStack(alignment: .leading, spacing: 2) {
                                Text(clip.name).lineLimit(2)
                                Text(String(format: "%d:%02d", Int(clip.duration) / 60, Int(clip.duration) % 60)).font(.caption).monospacedDigit().foregroundStyle(.secondary)
                            }.frame(maxWidth: .infinity, alignment: .leading)
                            HotkeyField(shortcut: state.soundShortcuts[clip.id], width: 100) { state.setHotkey("sound:" + clip.id.uuidString, $0) }
                            IconButton(symbol: "trash", title: L10n.text("삭제"), destructive: true) { deleting = clip }.disabled(state.speaking)
                        }.padding(.vertical, 8)
                    }
                }
            }
        }.alert(L10n.text("사운드를 삭제할까요?"), isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), presenting: deleting) { clip in
            Button(L10n.text("삭제"), role: .destructive) {
                do { try library.remove(clip); state.forgetSoundShortcut(clip.id) } catch { state.error = error.localizedDescription }
                deleting = nil
            }
            Button(L10n.text("취소"), role: .cancel) { deleting = nil }
        } message: { clip in Text(L10n.text("{0} 등록을 삭제합니다. 가져온 원본 파일은 유지됩니다.", clip.name)) }
    }
    private func importFiles(_ files: [URL], name: String?) {
        var errors: [String] = []
        for url in files {
            do { try library.importAudio(url, name: files.count == 1 ? name : nil, phraseNames: Array(state.ttsPhrases.entries.keys)) }
            catch { errors.append(url.lastPathComponent + ": " + error.localizedDescription) }
        }
        state.error = errors.isEmpty ? nil : errors.joined(separator: "\n")
    }
}

/// Name field, file picker and drop target shared by the soundboard and voice clone lists.
struct AudioAddForm<Extra: View>: View {
    let types: [UTType]
    let placeholder: String
    let add: ([URL], String?) -> Void
    @ViewBuilder var extra: () -> Extra
    @State private var files: [URL] = []
    @State private var name = ""
    @State private var targeted = false

    private var summary: String {
        switch files.count {
        case 0: return L10n.text("오디오 파일을 여기로 끌어다 놓거나 선택하세요.")
        case 1: return files[0].lastPathComponent
        default: return L10n.text("파일 {0}개 · 파일 이름으로 추가합니다.", String(files.count))
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "square.and.arrow.down").foregroundStyle(Theme.accent)
                Text(summary).font(.callout).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                Spacer()
                Button(L10n.text("파일 선택")) { _ = pick() }.controlSize(.small)
            }
            TextField(placeholder, text: $name).textFieldStyle(.roundedBorder).disabled(files.count > 1).onSubmit(finish)
            HStack(spacing: 8) {
                Spacer()
                extra()
                Button(action: finish) { Label(L10n.text("추가"), systemImage: "plus") }.buttonStyle(.borderedProminent)
            }
        }
        .padding(16)
        .background(targeted ? Theme.accent.opacity(0.08) : Color.clear, in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(targeted ? Theme.accent : Color.secondary.opacity(0.35), style: StrokeStyle(lineWidth: 1.5, dash: [6, 4])))
        .dropDestination(for: URL.self) { urls, _ in
            let accepted = urls.filter(accepts)
            if !accepted.isEmpty { choose(accepted) }
            return !accepted.isEmpty
        } isTargeted: { targeted = $0 }
    }

    private func accepts(_ url: URL) -> Bool {
        guard url.isFileURL, let type = UTType(filenameExtension: url.pathExtension) else { return false }
        return types.contains { type.conforms(to: $0) }
    }

    private func choose(_ urls: [URL]) {
        files = urls
        if urls.count == 1 { if name.trimmingCharacters(in: .whitespaces).isEmpty { name = urls[0].deletingPathExtension().lastPathComponent } }
        else { name = "" }
    }

    private func pick() -> Bool {
        let panel = NSOpenPanel(); panel.allowedContentTypes = types; panel.allowsMultipleSelection = true
        guard panel.runModal() == .OK, !panel.urls.isEmpty else { return false }
        choose(panel.urls); return true
    }

    private func finish() {
        // Without a chosen file, adding first asks for one so a typed name is never lost.
        if files.isEmpty && !pick() { return }
        let chosen = name.trimmingCharacters(in: .whitespacesAndNewlines)
        add(files, files.count == 1 && !chosen.isEmpty ? chosen : nil)
        files = []; name = ""
    }
}
