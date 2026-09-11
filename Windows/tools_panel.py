"""Bottom tool drawer and voice, phrase, and sound editors."""
import threading
import time
from PySide6.QtCore import Qt, QTimer, QPoint, QEvent, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import QFrame, QScrollArea, QWidget, QLineEdit, QPlainTextEdit, QComboBox
from config import CONTRACT, voice_ready
from widgets import label, column, row, button, divider, clear_layout

class ToolsPanel(QFrame):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app = app
        self.active = None
        self.voice_editor = None
        self.sound_controls = []
        self.setObjectName('toolsOverlay')
        self.backdrop = button('', self.dismiss); self.backdrop.setParent(self); self.backdrop.setObjectName('toolBackdrop')
        self.panel = QFrame(self); self.panel.setObjectName('toolDrawer')
        layout = column(self.panel, 24, 12)
        handle = QFrame(); handle.setFixedSize(32, 4); handle.setStyleSheet('background: #ccc; border-radius: 2px;')
        layout.addWidget(handle, alignment=Qt.AlignmentFlag.AlignHCenter)
        header = row(); self.title = label('', heading=True); self.title.setStyleSheet('font-size: 24px; font-weight: 700;')
        header.addWidget(self.title, 1); close = button('×', self.dismiss); close.setAccessibleName('닫기'); close.setFixedSize(30, 30); header.addWidget(close); layout.addLayout(header)
        area = QScrollArea(); area.setWidgetResizable(True); body = QWidget(); self.body = column(body, 0, 16); self.body.setAlignment(Qt.AlignmentFlag.AlignTop); area.setWidget(body); layout.addWidget(area, 1)
        self.animation = QPropertyAnimation(self.panel, b'pos', self); self.animation.setDuration(320); self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self.animation_finished)
        parent.installEventFilter(self); self.hide()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(watched.rect()); self.backdrop.setGeometry(self.rect()); self.panel.resize(self.width() - 24, self.height() - 88 - self.app.overlay_bottom)
        return False

    def toggle(self, key):
        if self.active == key:
            self.dismiss(); return
        self.animation.stop(); self.active = key
        self.title.setText(next(item['title'] for item in CONTRACT['tools'] if item['id'] == key))
        {'voice': self.show_voices, 'phrases': self.show_phrases, 'soundboard': self.show_sounds}[key]()
        self.setGeometry(self.parentWidget().rect()); self.backdrop.setGeometry(self.rect()); self.panel.resize(self.width() - 24, self.height() - 88 - self.app.overlay_bottom)
        self.show(); self.raise_(); self.panel.raise_()
        self.animation.setStartValue(QPoint(12, self.height())); self.animation.setEndValue(QPoint(12, 88)); self.animation.start()
        self.update_selection()

    def dismiss(self, animated=True):
        if self.app.voice_cancel: self.app.voice_cancel()
        self.animation.stop(); self.active = None; self.voice_editor = None
        self.update_selection()
        if animated and self.isVisible():
            self.animation.setStartValue(self.panel.pos()); self.animation.setEndValue(QPoint(12, self.height())); self.animation.start()
        else: self.hide()

    def animation_finished(self):
        if self.active is None: self.hide()

    def update_selection(self):
        for key, control in self.app.tool_buttons.items(): control.setChecked(key == self.active)

    def clear(self):
        if self.app.voice_cancel: self.app.voice_cancel()
        self.voice_editor = None; self.sound_controls = []
        clear_layout(self.body)
        return self.body

    def show_phrases(self, original=None):
        app = self.app
        layout = self.clear(); layout.addWidget(label('단축어', heading=True))
        shortcut = QLineEdit(original or ''); shortcut.setAccessibleName('단축어'); layout.addWidget(shortcut)
        layout.addWidget(label('읽을 문장', heading=True)); phrase = QPlainTextEdit(); phrase.setFixedHeight(64); phrase.setAccessibleName('읽을 문장')
        if original is not None: phrase.setPlainText(app.config['tts_phrases'][original])
        layout.addWidget(phrase); error = label(); error.setStyleSheet('color: #c33;'); error.hide()
        def save():
            try: app.save_tts_phrase(shortcut.text(), phrase.toPlainText(), original)
            except (ValueError, OSError) as reason: error.setText(str(reason)); error.show(); return
            self.show_phrases()
        controls = row(); controls.addWidget(button('추가' if original is None else '저장', save))
        if original is not None: controls.addWidget(button('취소', self.show_phrases))
        controls.addStretch(); layout.addLayout(controls); layout.addWidget(error); layout.addWidget(divider())
        if not app.config.get('tts_phrases'): layout.addWidget(label('저장된 단축어 없음', muted=True))
        def delete(key):
            try: app.delete_tts_phrase(key)
            except OSError as reason: error.setText(str(reason)); error.show(); return
            self.show_phrases()
        for key, value in sorted(app.config.get('tts_phrases', {}).items()):
            line = row(); detail = column(); detail.addWidget(label(key, heading=True)); detail.addWidget(label(value, muted=True)); line.addLayout(detail, 1)
            line.addWidget(button('수정', lambda k=key: self.show_phrases(k))); line.addWidget(button('삭제', lambda k=key: delete(k))); layout.addLayout(line)


    def show_voices(self):
        app = self.app
        layout = self.clear(); controls = row(); controls.addWidget(button('파일 추가', app.add_voice_files)); controls.addWidget(button('마이크 녹음', self.show_recording)); controls.addStretch(); layout.addLayout(controls)
        if not app.profiles: layout.addWidget(label('저장된 목소리 없음', muted=True))
        for profile in app.profiles:
            control = button((profile['name'] or profile.get('source_name', '목소리')) + ('' if voice_ready(profile, app.voice_root) else ' · 대본 필요') + '  ›', lambda p=profile: self.edit_voice(p)); control.setObjectName('nav'); layout.addWidget(control)


    def edit_voice(self, profile):
        app = self.app
        if app.tts_busy or app.voice_busy: app.status.setText('음성 작업이 끝난 뒤 수정하세요.'); return
        layout = self.clear(); layout.addWidget(button('‹ 목록', self.show_voices), alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(label('목소리명', heading=True)); name = QLineEdit(profile['name']); layout.addWidget(name)
        layout.addWidget(label('대본', heading=True)); transcript = QPlainTextEdit(profile['transcript']); transcript.setFixedHeight(110); layout.addWidget(transcript)
        state = label('', muted=True)
        def save():
            text = transcript.toPlainText().strip(); value = name.text().strip()
            if len(text) > CONTRACT['limits']['transcript']: state.setText('대본은 1,000자 이내로 입력해 주세요.'); return
            profile.update(name=value, transcript=text); app.save_profiles(); state.setText('등록 완료' if voice_ready(profile, app.voice_root) else '이름·대본 필요')
        name.textChanged.connect(save); transcript.textChanged.connect(save)
        line = row(); automatic = button('대본 자동 입력', lambda: app.transcribe_voice(profile)); line.addWidget(automatic)
        cancel = button('취소', lambda: app.voice_cancel() if app.voice_cancel else None); cancel.hide(); line.addWidget(cancel)
        line.addWidget(state, 1); remove = button('삭제', lambda: app.delete_voice(profile)); line.addWidget(remove); layout.addLayout(line)
        self.voice_editor = {'fields': [name, transcript, automatic, remove], 'state': state, 'cancel': cancel, 'profile': profile}
        state.setText('등록 완료' if voice_ready(profile, app.voice_root) else '이름·대본 필요')


    def show_recording(self):
        app = self.app
        if app.tts_busy or app.voice_busy or app.capture: app.status.setText('TTS와 STT를 멈춘 뒤 목소리를 추가하세요.'); return
        import sounddevice as sd
        layout = self.clear(); layout.addWidget(button('‹ 목록', self.show_voices), alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(label('대본 (선택)', heading=True)); transcript = QPlainTextEdit(); transcript.setFixedHeight(100); layout.addWidget(transcript)
        mic = QComboBox()
        for index, device in enumerate(sd.query_devices()):
            if device['max_input_channels'] > 0 and 'CABLE' not in device['name'].upper() and sd.query_hostapis(device['hostapi'])['name'] == 'Windows WASAPI': mic.addItem(device['name'], index)
        layout.addWidget(mic); hint = label('', muted=True); layout.addWidget(hint)
        state = {'stream': None, 'chunks': [], 'count': 0, 'start': 0}
        timer = QTimer(app.root)
        def stop_recording():
            timer.stop()
            if state['stream']: state['stream'].abort(); state['stream'].close(); state['stream'] = None
            app.voice_busy = False; app.update_busy()
        def cancel():
            stop_recording(); timer.deleteLater(); app.voice_cancel = None
        app.voice_cancel = cancel
        def record():
            import numpy as np
            if state['stream']:
                state['stream'].stop(); state['stream'].close(); state['stream'] = None; timer.stop()
                data = np.concatenate(state['chunks']) if state['chunks'] else np.zeros(0, dtype='float32')
                if not CONTRACT['limits']['recording_min'] <= len(data) / 24000 <= CONTRACT['limits']['recording_max']: hint.setText('3초 이상 녹음하세요.'); control.setText('녹음 시작'); stop_recording(); return
                details = ('녹음한 목소리', transcript.toPlainText().strip()); app.voice_cancel = None; timer.deleteLater()
                control.setEnabled(False); hint.setText('목소리 저장 중…')
                threading.Thread(target=app.store_voice, args=(details, data, None), daemon=True).start(); return
            try:
                if mic.currentIndex() < 0: raise ValueError('사용 가능한 물리 마이크가 없습니다.')
                state.update(chunks=[], count=0, start=time.monotonic())
                def callback(indata, frames, timestamp, status):
                    remaining = 24000 * CONTRACT['limits']['recording_max'] - state['count']
                    if remaining > 0: state['chunks'].append(indata[:remaining, 0].copy()); state['count'] += min(frames, remaining)
                state['stream'] = sd.InputStream(device=mic.currentData(), samplerate=24000, channels=1, dtype='float32', callback=callback, extra_settings=sd.WasapiSettings(auto_convert=True))
                state['stream'].start(); app.voice_busy = True; app.update_busy(); control.setText('완료'); timer.start(100)
            except Exception as error: hint.setText(str(error)); stop_recording()
        def tick():
            seconds = time.monotonic() - state['start']; hint.setText(f'녹음 중… {seconds:.1f} / 30초')
            if seconds >= CONTRACT['limits']['recording_max']: record()
        timer.timeout.connect(tick); control = button('녹음 시작', record)
        line = row(); line.addWidget(control); line.addWidget(button('취소', self.show_voices)); line.addStretch(); layout.addLayout(line)


    def set_voice_transcribing(self, active):
        if self.voice_editor is None:
            return
        editor = self.voice_editor
        for widget in editor['fields']:
            widget.setEnabled(not active)
        editor['cancel'].setVisible(active)
        editor['state'].setText('받아쓰는 중…' if active else ('등록 완료' if voice_ready(editor['profile'], self.app.voice_root) else '이름·대본 필요'))

    def show_sounds(self):
        app = self.app
        layout = self.clear(); line = row()
        add = button('파일 추가', app.add_sound_files); line.addWidget(add); line.addStretch()
        stop = button('재생 중지', app.cancel_tts); line.addWidget(stop); layout.addLayout(line)
        self.sound_controls = [(add, 'add', None), (stop, 'stop', None)]
        if app.soundboard.load_error:
            layout.addWidget(label(app.soundboard.load_error))
        elif not app.soundboard.clips:
            empty = label('등록된 사운드 없음', muted=True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter); empty.setContentsMargins(0, 24, 0, 24); layout.addWidget(empty)
        for clip in app.soundboard.clips:
            line = row(); play = button('재생', lambda item=clip: app.cancel_tts() if app.playing_sound == item['id'] else app.play_sound(item))
            play.setAccessibleName(clip['name'] + ' 재생'); line.addWidget(play)
            details = column(spacing=4); details.addWidget(label(clip['name'], heading=True))
            seconds = int(clip['duration']); details.addWidget(label(f'{seconds // 60}:{seconds % 60:02d}', muted=True)); line.addLayout(details, 1)
            remove = button('삭제', lambda item=clip: app.delete_sound(item)); line.addWidget(remove); layout.addLayout(line)
            self.sound_controls.extend([(play, 'play', clip['id']), (remove, 'remove', clip['id'])])
        self.update_sound_controls()

    def update_sound_controls(self):
        app = self.app
        for control, role, ident in self.sound_controls:
            if role == 'play':
                control.setText('중지' if app.playing_sound == ident else '재생')
                control.setEnabled(app.tts_enabled.isChecked() and not app.voice_busy and (not app.tts_busy or app.playing_sound == ident))
            elif role == 'stop': control.setVisible(app.playing_sound is not None)
            else: control.setEnabled(not (app.tts_busy or app.voice_busy or app.soundboard.load_error))
