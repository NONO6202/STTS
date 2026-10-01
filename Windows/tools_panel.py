"""Bottom tool drawer and voice, phrase, and sound editors."""
import threading
import time
from localization import tr, message as localize_message

from PySide6.QtCore import Qt, QTimer, QPoint, QEvent, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QScrollArea, QWidget, QLineEdit, QPlainTextEdit, QComboBox, QLabel
from config import CONTRACT, voice_ready
from widgets import label, column, row, button, styled, restyle, section, clear_layout, icon_button, icon_for
from theme import P, ACCENT, on_change

def caption(text):
    result = label(text); result.setWordWrap(False); return result


def symbol_button(text, symbol, callback, name=''):
    control = styled(button(text, callback), name) if name else button(text, callback)
    on_change(lambda: control.setIcon(icon_for(symbol, 'white' if name in ('primary', 'record') else (ACCENT if name == 'link' else P['text']))))
    return control


def back_button(callback):
    return symbol_button(tr('목록'), 'chevron.left', callback, 'link')


def status_badge(text, ok):
    result = label(text); result.setWordWrap(False); result.setProperty('badge', 'ok' if ok else 'warn'); return result


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
        layout = column(self.panel, 24, 10); layout.setContentsMargins(24, 8, 24, 0)
        handle = QFrame(); handle.setObjectName('grabber'); handle.setFixedSize(36, 4)
        layout.addWidget(handle, alignment=Qt.AlignmentFlag.AlignHCenter)
        header = row(); self.title = label('', title=True)
        header.addWidget(self.title, 1); close = styled(button('', self.dismiss), 'close'); close.setAccessibleName(tr('닫기')); close.setToolTip(tr('닫기'))
        on_change(lambda: close.setIcon(icon_for('xmark', P['secondary'], 12))); header.addWidget(close); layout.addLayout(header)
        area = QScrollArea(); area.setWidgetResizable(True); body = QWidget(); self.body = column(body, 0, 18); self.body.setContentsMargins(0, 8, 0, 24); self.body.setAlignment(Qt.AlignmentFlag.AlignTop); area.setWidget(body); layout.addWidget(area, 1)
        self.animation = QPropertyAnimation(self.panel, b'pos', self); self.animation.setDuration(320); self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self.animation_finished)
        parent.installEventFilter(self); self.hide()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(watched.rect()); self.backdrop.setGeometry(self.rect()); self.panel.resize(self.width() - 24, self.height() - 80 - self.app.overlay_bottom)
        return False

    def toggle(self, key):
        if self.active == key:
            self.dismiss(); return
        self.animation.stop(); self.active = key
        self.title.setText(localize_message(next(item['title'] for item in CONTRACT['tools'] if item['id'] == key)))
        {'voice': self.show_voices, 'phrases': self.show_phrases, 'soundboard': self.show_sounds}[key]()
        self.setGeometry(self.parentWidget().rect()); self.backdrop.setGeometry(self.rect()); self.panel.resize(self.width() - 24, self.height() - 80 - self.app.overlay_bottom)
        self.show(); self.raise_(); self.panel.raise_()
        self.animation.setStartValue(QPoint(12, self.height())); self.animation.setEndValue(QPoint(12, 80)); self.animation.start()
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
        layout = self.clear(); editor = section(layout)
        line = row(); line.addWidget(label(tr('단축어')), 1)
        shortcut = QLineEdit(original or ''); shortcut.setAccessibleName(tr('단축어')); shortcut.setFixedWidth(240); line.addWidget(shortcut); editor.addLayout(line)
        text = column(spacing=8); text.addWidget(caption(tr('읽을 문장')))
        phrase = QPlainTextEdit(); phrase.setFixedHeight(64); phrase.setAccessibleName(tr('읽을 문장')); text.addWidget(phrase); editor.addLayout(text)
        if original is not None: phrase.setPlainText(app.config['tts_phrases'][original])
        error = label(tone='danger'); error.hide()
        def save():
            try: app.save_tts_phrase(shortcut.text(), phrase.toPlainText(), original)
            except (ValueError, OSError) as reason: error.setText(localize_message(str(reason))); error.show(); return
            self.show_phrases()
        controls = row(); controls.addWidget(error, 1); controls.addStretch()
        if original is not None: controls.addWidget(button(tr('취소'), self.show_phrases))
        controls.addWidget(styled(button(localize_message('추가' if original is None else '저장'), save), 'primary')); editor.addLayout(controls)
        saved = section(layout)
        if not app.config.get('tts_phrases'): saved.addWidget(label(tr('저장된 단축어 없음'), muted=True))
        def delete(key):
            try: app.delete_tts_phrase(key)
            except OSError as reason: error.setText(localize_message(str(reason))); error.show(); return
            self.show_phrases()
        for key, value in sorted(app.config.get('tts_phrases', {}).items()):
            line = row(); line.setSpacing(12); detail = column(spacing=3); detail.addWidget(label(key, heading=True)); detail.addWidget(label(value, muted=True)); line.addLayout(detail, 1)
            line.addWidget(icon_button('pencil', tr('수정'), lambda k=key: self.show_phrases(k)))
            line.addWidget(icon_button('trash', tr('삭제'), lambda k=key: delete(k), destructive=True))
            holder = saved.addLayout(line)
            if key == original: holder.setObjectName('highlight'); holder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout.addStretch()


    def show_voices(self):
        app = self.app
        layout = self.clear(); controls = row()
        controls.addWidget(symbol_button(tr('파일 추가'), 'plus', app.add_voice_files)); controls.addWidget(symbol_button(tr('마이크 녹음'), 'mic', self.show_recording)); controls.addStretch(); layout.addLayout(controls)
        voices = section(layout)
        if not app.profiles: voices.addWidget(label(tr('저장된 목소리 없음'), muted=True))
        for profile in app.profiles:
            ready = voice_ready(profile, app.voice_root); name = profile['name'] or profile.get('source_name', tr('목소리'))
            control = styled(button('', lambda p=profile: self.edit_voice(p)), 'nav'); control.setAccessibleName(name)
            content = row(); content.setContentsMargins(0, 0, 0, 0); content.setSpacing(10); control.setLayout(content)
            parts = [QLabel(), label(name)]
            on_change(lambda icon=parts[0]: icon.setPixmap(icon_for('person.wave.2', ACCENT, 18).pixmap(18, 18)))
            if not ready: parts.append(status_badge(tr('대본 필요'), False))
            arrow = QLabel(); on_change(lambda: arrow.setPixmap(icon_for('chevron.right', P['tertiary'], 12).pixmap(12, 12))); parts.append(arrow)
            for index, part in enumerate(parts):
                part.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents); content.addWidget(part, 1 if index == 1 else 0)
            control.setMinimumHeight(28); voices.addWidget(control)
        layout.addStretch()


    def edit_voice(self, profile):
        app = self.app
        if app.tts_busy or app.voice_busy: app.status.setText(tr('음성 작업이 끝난 뒤 수정하세요.')); return
        layout = self.clear(); layout.addWidget(back_button(self.show_voices), alignment=Qt.AlignmentFlag.AlignLeft)
        editor = section(layout)
        line = row(); line.addWidget(label(tr('목소리명')), 1); name = QLineEdit(profile['name']); name.setPlaceholderText(tr('목소리명')); name.setFixedWidth(240); line.addWidget(name); editor.addLayout(line)
        text = column(spacing=8); text.addWidget(caption(tr('대본'))); transcript = QPlainTextEdit(profile['transcript']); transcript.setPlaceholderText(tr('음성의 대본')); transcript.setFixedHeight(110); text.addWidget(transcript); editor.addLayout(text)
        state = status_badge('', False)
        def describe():
            ready = voice_ready(profile, app.voice_root)
            state.setText(localize_message('등록 완료' if ready else '이름·대본 필요')); restyle(state, badge='ok' if ready else 'warn')
        def save():
            text = transcript.toPlainText().strip(); value = name.text().strip()
            if len(text) > CONTRACT['limits']['transcript']: state.setText(tr('대본은 1,000자 이내로 입력해 주세요.')); return
            profile.update(name=value, transcript=text); app.save_profiles(); describe()
        name.textChanged.connect(save); transcript.textChanged.connect(save)
        line = row(); automatic = button(tr('대본 자동 입력'), lambda: app.transcribe_voice(profile)); line.addWidget(automatic)
        cancel = button(tr('취소'), lambda: app.voice_cancel() if app.voice_cancel else None); cancel.hide(); line.addWidget(cancel)
        line.addWidget(state); line.addStretch(); remove = icon_button('trash', tr('삭제'), lambda: app.delete_voice(profile), destructive=True); line.addWidget(remove); editor.addLayout(line)
        self.voice_editor = {'fields': [name, transcript, automatic, remove], 'state': state, 'cancel': cancel, 'profile': profile, 'describe': describe}
        layout.addStretch()
        describe()


    def show_recording(self):
        app = self.app
        if app.tts_busy or app.voice_busy or app.capture: app.status.setText(tr('TTS와 STT를 멈춘 뒤 목소리를 추가하세요.')); return
        import sounddevice as sd
        layout = self.clear(); layout.addWidget(back_button(self.show_voices), alignment=Qt.AlignmentFlag.AlignLeft)
        recorder = section(layout)
        transcript = QPlainTextEdit(); transcript.setPlaceholderText(tr('대본 (선택)')); transcript.setFixedHeight(100); recorder.addWidget(transcript)
        mic = QComboBox(); mic.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for index, device in enumerate(sd.query_devices()):
            if device['max_input_channels'] > 0 and 'CABLE' not in device['name'].upper() and sd.query_hostapis(device['hostapi'])['name'] == 'Windows WASAPI': mic.addItem(device['name'], index)
        line = row(); line.addWidget(label(tr('마이크')), 1); line.addWidget(mic); recorder.addLayout(line); hint = label('', muted=True)
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
                if not CONTRACT['limits']['recording_min'] <= len(data) / 24000 <= CONTRACT['limits']['recording_max']: hint.setText(tr('3초 이상 녹음하세요.')); recording(False); stop_recording(); return
                details = (tr('녹음한 목소리'), transcript.toPlainText().strip()); app.voice_cancel = None; timer.deleteLater()
                control.setEnabled(False); hint.setText(tr('목소리 저장 중…'))
                threading.Thread(target=app.store_voice, args=(details, data, None), daemon=True).start(); return
            try:
                if mic.currentIndex() < 0: raise ValueError('사용 가능한 물리 마이크가 없습니다.')
                state.update(chunks=[], count=0, start=time.monotonic())
                def callback(indata, frames, timestamp, status):
                    remaining = 24000 * CONTRACT['limits']['recording_max'] - state['count']
                    if remaining > 0: state['chunks'].append(indata[:remaining, 0].copy()); state['count'] += min(frames, remaining)
                state['stream'] = sd.InputStream(device=mic.currentData(), samplerate=24000, channels=1, dtype='float32', callback=callback, extra_settings=sd.WasapiSettings(auto_convert=True))
                state['stream'].start(); app.voice_busy = True; app.update_busy(); recording(True); timer.start(100)
            except Exception as error: hint.setText(localize_message(str(error))); stop_recording()
        def tick():
            seconds = time.monotonic() - state['start']; hint.setText(localize_message(f'녹음 중… {seconds:.1f} / 30초'))
            if seconds >= CONTRACT['limits']['recording_max']: record()
        timer.timeout.connect(tick); control = symbol_button(tr('녹음 시작'), 'record.circle', record, 'record')
        def recording(active):
            # Idle shows the red record button; while recording it becomes the prominent "done" action, as on macOS.
            control.setText(tr('완료' if active else '녹음 시작')); control.setIcon(icon_for('record.circle', 'white') if not active else QIcon())
            control.setObjectName('primary' if active else 'record'); restyle(control)
        line = row(); line.addWidget(hint, 1); line.addWidget(button(tr('취소'), self.show_voices)); line.addWidget(control); recorder.addLayout(line)
        layout.addStretch()


    def set_voice_transcribing(self, active):
        if self.voice_editor is None:
            return
        editor = self.voice_editor
        for widget in editor['fields']:
            widget.setEnabled(not active)
        editor['cancel'].setVisible(active)
        if active: editor['state'].setText(localize_message('받아쓰는 중…')); restyle(editor['state'], badge='')
        else: editor['describe']()

    def show_sounds(self):
        app = self.app
        layout = self.clear(); line = row()
        add = symbol_button(tr('파일 추가'), 'plus', app.add_sound_files); line.addWidget(add); line.addStretch()
        stop = symbol_button(tr('재생 중지'), 'stop.fill', app.cancel_tts); line.addWidget(stop); layout.addLayout(line)
        self.sound_controls = [(add, 'add', None), (stop, 'stop', None)]
        if app.soundboard.load_error:
            layout.addWidget(label(localize_message(app.soundboard.load_error), tone='danger'))
        elif not app.soundboard.clips:
            empty = QWidget(); body = column(empty, 0, 10); body.setContentsMargins(0, 40, 0, 40)
            icon = QLabel(); icon.setAlignment(Qt.AlignmentFlag.AlignCenter); on_change(lambda: icon.setPixmap(icon_for('square.grid.2x2', P['tertiary'], 28).pixmap(28, 28)))
            text = label(tr('등록된 사운드 없음'), muted=True); text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            body.addWidget(icon); body.addWidget(text); layout.addWidget(empty)
        clips = section(layout) if app.soundboard.clips else None
        for clip in app.soundboard.clips:
            line = row(); line.setSpacing(12)
            play = styled(button('', lambda item=clip: app.cancel_tts() if app.playing_sound == item['id'] else app.play_sound(item)), 'play')
            play.setAccessibleName(localize_message(clip['name'] + ' 재생')); line.addWidget(play)
            details = column(spacing=2); details.addWidget(label(clip['name']))
            seconds = int(clip['duration']); details.addWidget(label(f'{seconds // 60}:{seconds % 60:02d}', muted=True)); line.addLayout(details, 1)
            remove = icon_button('trash', tr('삭제'), lambda item=clip: app.delete_sound(item), destructive=True); line.addWidget(remove); clips.addLayout(line)
            self.sound_controls.extend([(play, 'play', clip['id']), (remove, 'remove', clip['id'])])
        layout.addStretch()
        self.update_sound_controls()

    def update_sound_controls(self):
        app = self.app
        for control, role, ident in self.sound_controls:
            if role == 'play':
                playing = app.playing_sound == ident
                control.setObjectName('playing' if playing else 'play'); restyle(control)
                control.setIcon(icon_for('stop.fill' if playing else 'play.fill', 'white' if playing else ACCENT, 12))
                control.setEnabled(app.tts_enabled.isChecked() and not app.voice_busy and (not app.tts_busy or app.playing_sound == ident))
            elif role == 'stop': control.setVisible(app.playing_sound is not None)
            else: control.setEnabled(not (app.tts_busy or app.voice_busy or app.soundboard.load_error))
