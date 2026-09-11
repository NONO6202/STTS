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
        VStack(alignment: .leading, spacing: 12) {
            Text("단축어").font(.headline)
            TextField("", text: $shortcut).textFieldStyle(.roundedBorder).accessibilityLabel("단축어")
            Text("읽을 문장").font(.headline)
            TextField("", text: $phrase, axis: .vertical)
                .lineLimit(3...5).textFieldStyle(.roundedBorder).accessibilityLabel("읽을 문장")
            HStack {
                Button(editing == nil ? "추가" : "저장") {
                    do {
                        try phrases.save(shortcut: shortcut, phrase: phrase, replacing: editing, soundNames: soundNames)
                        clearEditor()
                    } catch { self.error = error.localizedDescription }
                }
                if editing != nil { Button("취소", action: clearEditor) }
                Spacer()
            }
            if let error { Text(error).font(.caption).foregroundStyle(.red) }
            Divider().padding(.vertical, 4)
            if phrases.entries.isEmpty { Text("저장된 단축어 없음").foregroundStyle(.secondary) }
            ForEach(phrases.entries.keys.sorted(), id: \.self) { key in
                HStack(alignment: .top, spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(key).font(.headline).lineLimit(2)
                        Text(phrases.entries[key] ?? "").foregroundStyle(.secondary).lineLimit(3)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                    Button("수정") { editing = key; shortcut = key; phrase = phrases.entries[key] ?? ""; error = nil }
                    Button("삭제", role: .destructive) {
                        phrases.remove(key)
                        if editing == key { clearEditor() }
                    }
                }.padding(.vertical, 6)
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
        VStack(alignment: .leading, spacing: 16) {
            if recordingPage {
                Button { editingID = state.cancelVoiceRecording(); recordingPage = false } label: { Label("목록", systemImage: "chevron.left") }
                TextField("대본 (선택)", text: $state.voiceRecordingTranscript, axis: .vertical)
                    .lineLimit(4...7).textFieldStyle(.roundedBorder).disabled(state.voiceTranscribing)
                HStack {
                    if state.voiceRecordingActive {
                        Circle().fill(.red).frame(width: 8, height: 8)
                        Text("녹음 중 · \(state.voiceRecordingSeconds, specifier: "%.1f") / 30초").monospacedDigit()
                    } else if state.voiceTranscribing { ProgressView().controlSize(.small); Text("받아쓰는 중…") }
                    else if state.voiceRecordingPending { Text("마이크 준비 중…") }
                    Spacer()
                    if state.voiceRecordingBusy {
                        if !state.voiceTranscribing { Button("완료") { state.finishVoiceRecording() }.disabled(!state.voiceRecordingActive || state.voiceRecordingSeconds < 3) }
                        Button("취소") { editingID = state.cancelVoiceRecording(); recordingPage = false }
                    } else {
                        Button("녹음 시작") { state.startVoiceRecording { editingID = $0; recordingPage = false } }
                    }
                }
            } else if let id = editingID, let index = state.clonedVoices.firstIndex(where: { $0.id == id }) {
                Button { editingID = nil } label: { Label("목록", systemImage: "chevron.left") }
                Text("목소리명").font(.headline)
                TextField("목소리명", text: $state.clonedVoices[index].name).textFieldStyle(.roundedBorder).disabled(state.voiceTranscribing)
                Text("대본").font(.headline)
                TextField("음성의 대본", text: $state.clonedVoices[index].transcript, axis: .vertical)
                    .lineLimit(4...7).textFieldStyle(.roundedBorder).disabled(state.voiceTranscribing)
                HStack {
                    if state.voiceTranscribing {
                        ProgressView().controlSize(.small)
                        Text("받아쓰는 중…").font(.caption)
                        Button("취소") { state.cancelVoiceRecording() }
                    } else {
                        Button("대본 자동 입력") { state.transcribeVoice(id) }.disabled(state.modelWorkIsBusy)
                        Text(state.clonedVoices[index].ready ? "등록 완료" : "이름·대본 필요").font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("삭제", role: .destructive) { voiceToDelete = state.clonedVoices[index] }.disabled(state.voiceTranscribing)
                }
            } else {
                HStack {
                    Button("파일 추가") { editingID = state.addClonedVoices() }.disabled(state.modelWorkIsBusy)
                    Button("마이크 녹음") { state.voiceRecordingTranscript = ""; recordingPage = true }.disabled(state.modelWorkIsBusy)
                }
                if state.clonedVoices.isEmpty { Text("저장된 목소리 없음").foregroundStyle(.secondary) }
                ForEach(state.clonedVoices) { voice in
                    Button { editingID = voice.id } label: {
                        HStack {
                            Text(voice.name.isEmpty ? voice.sourceName : voice.name)
                            Spacer()
                            if !voice.ready { Text("대본 필요").font(.caption).foregroundStyle(.secondary) }
                            Image(systemName: "chevron.right").foregroundStyle(.secondary)
                        }.padding(.vertical, 10).contentShape(Rectangle())
                    }.buttonStyle(.plain)
                }
            }
        }.disabled(state.speaking)
            .alert("목소리를 삭제할까요?", isPresented: Binding(get: { voiceToDelete != nil }, set: { if !$0 { voiceToDelete = nil } }), presenting: voiceToDelete) { voice in
                Button("삭제", role: .destructive) { state.deleteClonedVoice(voice.id); editingID = nil; voiceToDelete = nil }
                Button("취소", role: .cancel) { voiceToDelete = nil }
            } message: { voice in Text(voice.name + " 목소리를 휴지통으로 이동합니다.") }
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
        VStack(spacing: 12) {
            Capsule().fill(.tertiary).frame(width: 32, height: 4).padding(.top, 10)
            HStack {
                Text(title).font(.system(size: 24, weight: .bold))
                Spacer()
                Button(action: close) { Image(systemName: "xmark").font(.system(size: 12, weight: .bold)).frame(width: 30, height: 30).background(.primary.opacity(0.06), in: Circle()) }.buttonStyle(.plain).accessibilityLabel("닫기").keyboardShortcut(.cancelAction)
            }.padding(.horizontal, 24)
            ScrollView {
                Group {
                    switch tool {
                    case "voice": VoiceLibraryView(state: state)
                    case "phrases": TTSShortcutsView(phrases: $state.ttsPhrases, soundNames: state.soundboard.clips.map(\.name))
                    default: SoundboardView(state: state, library: state.soundboard)
                    }
                }.frame(maxWidth: .infinity, alignment: .topLeading).padding(24)
            }
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color(nsColor: .windowBackgroundColor), in: UnevenRoundedRectangle(topLeadingRadius: 24, topTrailingRadius: 24))
            .shadow(color: .black.opacity(0.12), radius: 18, y: -4)
    }
}

private struct SoundboardView: View {
    @ObservedObject var state: AppState
    @ObservedObject var library: SoundboardLibrary
    @State private var deleting: SoundboardClip?
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Button("파일 추가", action: importFiles).disabled(state.speaking || state.voiceRecordingBusy || state.managingModels || library.loadError != nil)
                Spacer()
                if state.playingSoundID != nil { Button("재생 중지") { state.cancelSpeech() } }
            }
            if let error = library.loadError { Text(error).foregroundStyle(.red) }
            if library.clips.isEmpty && library.loadError == nil {
                VStack(spacing: 10) {
                    Image(systemName: "square.grid.2x2").font(.system(size: 26)).foregroundStyle(.secondary)
                    Text("등록된 사운드 없음")
                }.frame(maxWidth: .infinity).padding(.vertical, 32)
            }
            ForEach(library.clips) { clip in
                HStack(spacing: 12) {
                    Button {
                        if state.playingSoundID == clip.id { state.cancelSpeech() }
                        else { state.playSound(clip, from: library.audioURL(clip)) }
                    } label: {
                        Image(systemName: state.playingSoundID == clip.id ? "stop.fill" : "play.fill")
                            .frame(width: 28, height: 28)
                    }.accessibilityLabel(state.playingSoundID == clip.id ? "재생 중지" : clip.name + " 재생")
                        .disabled(!state.ttsEnabled || state.voiceRecordingBusy || (state.speaking && state.playingSoundID != clip.id))
                    VStack(alignment: .leading, spacing: 4) {
                        Text(clip.name).lineLimit(2)
                        Text(String(format: "%d:%02d", Int(clip.duration) / 60, Int(clip.duration) % 60)).font(.caption).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                    Button("삭제", role: .destructive) { deleting = clip }.disabled(state.speaking)
                }.padding(12).background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 10))
            }
        }.alert("사운드를 삭제할까요?", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), presenting: deleting) { clip in
            Button("삭제", role: .destructive) {
                do { try library.remove(clip) } catch { state.error = error.localizedDescription }
                deleting = nil
            }
            Button("취소", role: .cancel) { deleting = nil }
        } message: { clip in Text(clip.name + " 등록을 삭제합니다. 가져온 원본 파일은 유지됩니다.") }
    }
    private func importFiles() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.audio]; panel.allowsMultipleSelection = true
        guard panel.runModal() == .OK else { return }
        var errors: [String] = []
        for url in panel.urls {
            do { try library.importAudio(url, phraseNames: Array(state.ttsPhrases.entries.keys)) }
            catch { errors.append(url.lastPathComponent + ": " + error.localizedDescription) }
        }
        state.error = errors.isEmpty ? nil : errors.joined(separator: "\n")
    }
}
