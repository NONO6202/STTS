"""STTS Windows UI; the speech engines and stored user data are platform-local."""
import base64
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
import uuid
import unicodedata

from PySide6.QtCore import Qt, QTimer, QPoint, QSize, QEvent
from PySide6.QtGui import QColor, QFont, QCursor, QKeyEvent, QInputMethodEvent
from PySide6.QtWidgets import QApplication, QWidget, QFrame, QLabel, QPushButton, QComboBox, QSlider, QScrollArea, QStackedWidget, QHBoxLayout, QButtonGroup, QColorDialog, QFileDialog, QMessageBox, QSystemTrayIcon, QMenu, QToolTip, QDialog, QGraphicsDropShadowEffect, QListWidget, QListWidgetItem

from config import CONTRACT, VERSION, DEFAULTS, TTS_MODELS, STT_MODELS, SPEECH_LANGUAGES, data_directory, write_json, voice_ready
from widgets import STYLE, label, column, row, button, divider, icon_for, Bridge, MainWindow, ComposerWindow, ComposerEdit, ShortcutFilter, StatusMessage, CheckBox, ColorWell, card
from settings import SettingsPanel
from tools_panel import ToolsPanel
from soundboard import SoundboardLibrary

DATA = data_directory()


class App:
    def __init__(self, root, smoke=False):
        from winutil import ChildJob
        self.root, self.smoke = root, smoke; root.owner = self
        self.closing = False; self.config = dict(DEFAULTS)
        DATA.mkdir(parents=True, exist_ok=True)
        self.model_root, self.voice_root = DATA / 'Models', DATA / 'Voice'
        self.model_root.mkdir(exist_ok=True); self.voice_root.mkdir(exist_ok=True)
        try: self.config.update(json.loads((DATA / 'settings.json').read_text(encoding='utf-8')))
        except (OSError, ValueError): pass
        try: self.profiles = json.loads((self.voice_root / 'profiles.json').read_text(encoding='utf-8'))
        except (OSError, ValueError): self.profiles = []
        if 'selected_clone_id' not in self.config:
            old = next((p for p in self.profiles if '클론 · ' + p['name'] == self.config['voice']), None)
            self.config['selected_clone_id'] = old['id'] if old else None
        self.capture = self.hotkeys = self.composer = self.caption = self.tray = None
        self.voice_cancel = None; self.recording_key = None; self.shortcut_buttons = {}; self.boxes = {}; self.color_buttons = {}; self.voice_sliders = {}
        self.tts_busy = self.voice_busy = False; self.audio_stop = threading.Event()
        self.backends = {}; self.caption_history = []
        self.soundboard = SoundboardLibrary(DATA / "Soundboard"); self.playing_sound = None
        self.job = ChildJob(); self.tts_worker = self.make_tts_worker()
        root.setObjectName('main'); root.setWindowTitle('STTS'); root.setFixedSize(CONTRACT['window']['width'], CONTRACT['window']['height']); root.setStyleSheet(STYLE)
        # A second launch must be able to find the window even before it has ever been shown.
        root.winId()
        self.bridge = Bridge(self, root)
        layout = column(root, spacing=0)
        segments = self.navigation = QFrame(root); segments.setObjectName('segments'); segment_layout = QHBoxLayout(segments)
        segment_layout.setContentsMargins(4, 4, 4, 4); segment_layout.setSpacing(4)
        self.tab_buttons = QButtonGroup(root); self.tab_buttons.setExclusive(True)
        for index, title in enumerate(CONTRACT['tabs']):
            control = QPushButton(title); control.setObjectName('segment'); control.setFixedHeight(32); control.setCheckable(True); control.setIcon(icon_for(title))
            self.tab_buttons.addButton(control, index); segment_layout.addWidget(control, 1)
        self.tab_buttons.idClicked.connect(self.select_tab); self.tab_buttons.button(0).setChecked(True)
        segments.setFixedSize(CONTRACT['window']['tabs_width'], 40)
        segments.move((root.width() - segments.width()) // 2, 12)
        self.content = QWidget(); content_layout = column(self.content)
        self.tabs = QStackedWidget(); content_layout.addWidget(self.tabs); layout.addWidget(self.content, 1)
        self.status_slot = QWidget(root); status_layout = column(self.status_slot, 0, 0); status_layout.setContentsMargins(24, 0, 24, 8)
        self.status = StatusMessage(self.status_slot); status_layout.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.status_slot.hide()
        self.tts_cancel = button('취소', self.cancel_tts); self.tts_cancel.setFixedHeight(24); self.status.layout().insertWidget(1, self.tts_cancel); self.tts_cancel.hide()
        self.tts_page, self.tts_layout = self.page(); self.stt_page, self.stt_layout = self.page(); self.settings_page, self.settings_layout = self.page()
        for page in (self.tts_page, self.stt_page, self.settings_page): self.tabs.addWidget(page)
        self.tts_layout.setSpacing(20); self.settings_layout.setSpacing(16)
        footer_panel = self.footer = QFrame(root); footer_panel.setObjectName('segments'); footer_panel.setFixedSize(CONTRACT['window']['tabs_width'], 40)
        footer_layout = QHBoxLayout(footer_panel); footer_layout.setContentsMargins(4, 4, 4, 4); footer_layout.setSpacing(4)
        self.tool_buttons = {}
        for item in CONTRACT['tools']:
            control = button(item['title'], lambda key=item['id']: self.tools.toggle(key)); control.setObjectName('segment'); control.setCheckable(True); control.setIcon(icon_for(item['title'])); control.setFixedHeight(32)
            self.tool_buttons[item['id']] = control; footer_layout.addWidget(control, 1)
        for bar in (segments, footer_panel):
            shadow = QGraphicsDropShadowEffect(bar); shadow.setBlurRadius(12); shadow.setOffset(0, 2); shadow.setColor(QColor(31, 49, 75, 24)); bar.setGraphicsEffect(shadow)
        self.tools = ToolsPanel(self, self.content)
        self.settings = SettingsPanel(self)
        self.make_tts(); self.make_stt(); self.settings.show_menu()
        self.shortcut_filter = ShortcutFilter(self); QApplication.instance().installEventFilter(self.shortcut_filter)
        self.caption_timer = QTimer(root); self.caption_timer.setSingleShot(True); self.caption_timer.timeout.connect(self.clear_caption)
        self.composer_timer = QTimer(root); self.composer_timer.timeout.connect(self.composer_tick)
        self.status.changed.connect(self.layout_overlays)
        self.navigation.raise_()
        self.update_busy()
        if not smoke:
            try: self.register_hotkeys()
            except RuntimeError as error: self.status.setText(str(error))
            self.make_tray()
            if not self.config.get('setup_completed'): QTimer.singleShot(500, self.show_setup)

    def page(self):
        area = QScrollArea(); area.setWidgetResizable(True)
        content = QWidget(); layout = column(content, CONTRACT['window']['padding'], CONTRACT['window']['spacing']); layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        padding = CONTRACT['window']['padding']; layout.setContentsMargins(padding, padding + 60, padding, padding)
        area.setWidget(content); return area, layout

    def post(self, callback, *args):
        if not self.closing: self.bridge.dispatch.emit(callback, args)
    def report(self, message, active=None):
        def deliver():
            if active is not None and not active(): return
            if message.startswith(('TTS · ', 'STT · ')): self.backend_changed(message)
            else: self.status.setText(message)
        self.post(deliver)
    def make_tts_worker(self):
        from audio import Worker
        worker = Worker(self.job, lambda message: self.report(message,
            active=lambda: self.tts_worker is worker and self.tts_busy and not self.audio_stop.is_set()))
        return worker
    def backend_changed(self, message):
        self.backends[message.split(' · ')[0]] = message
    def save(self): write_json(DATA / 'settings.json', self.config)

    def option(self, layout, title, key, values, changed=None):
        line = row(); caption = label(title); caption.setWordWrap(False); caption.setMinimumWidth(64); line.addWidget(caption)
        box = QComboBox(); box.addItems(values); box.setCurrentText(str(self.config[key])); box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents); line.addWidget(box, 1)
        def update(value):
            self.config[key] = value; self.save()
            if changed: changed()
        box.currentTextChanged.connect(update); layout.addLayout(line); self.boxes[key] = box
        return box, line

    def check(self, layout, title, key, changed=None):
        control = CheckBox(title); control.setChecked(bool(self.config[key]))
        def update(enabled):
            try:
                if changed: changed(enabled)
                self.config[key] = enabled; self.save()
            except Exception as error:
                control.blockSignals(True); control.setChecked(self.config[key]); control.blockSignals(False); self.status.setText(str(error))
        control.toggled.connect(update); layout.addWidget(control); return control

    def scale(self, layout, title, key, changed=None, *, minimum=0, maximum=100, factor=100, suffix='%'):
        line = row(); line.addWidget(label(title))
        slider = QSlider(Qt.Orientation.Horizontal); slider.setRange(minimum, maximum); slider.setValue(round(self.config[key] * factor))
        format_value = lambda value: f'{value / factor:.2f}×' if key == 'speed' else f'{value}{suffix}'
        number = label(format_value(slider.value())); number.setFixedWidth(42); number.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        def update(value):
            self.config[key] = value / factor; number.setText(format_value(value))
            if changed: changed()
            if not slider.isSliderDown(): self.save()
        slider.valueChanged.connect(update); slider.sliderReleased.connect(self.save)
        line.addWidget(slider, 1); line.addWidget(number); layout.addLayout(line)
        if key in ('volume', 'pitch', 'speed'): self.voice_sliders[key] = slider

    def reset_voice_controls(self):
        for key, value in [('volume', 100), ('pitch', 0), ('speed', 100)]: self.voice_sliders[key].setValue(value)

    def shortcut_row(self, layout, title, key):
        from winutil import shortcut_label
        line = row(); line.addWidget(label(title)); line.addStretch()
        control = button(shortcut_label(self.config[key]), lambda: self.record_shortcut(key)); control.setFixedWidth(190)
        self.shortcut_buttons[key] = control; line.addWidget(control); layout.addLayout(line)

    def record_shortcut(self, key):
        if self.recording_key: self.finish_shortcut(); return
        if self.hotkeys: self.hotkeys.close(); self.hotkeys = None
        self.recording_key = key; self.shortcut_buttons[key].setText('키를 누르세요 · Esc 취소')
    def finish_shortcut(self, candidate=None, error=None):
        from winutil import shortcut_label, shortcut_data
        key = self.recording_key
        if not key: return
        self.recording_key = None; old = self.config[key]
        try:
            if error: raise error
            if candidate is not None:
                if any(shortcut_data(self.config[k]) == candidate for k in ('composer_key', 'stt_key') if k != key):
                    raise ValueError('다른 기능과 겹치지 않는 단축키를 선택해 주세요.')
                self.config[key] = candidate
            self.register_hotkeys()
            if candidate is not None: self.save()
        except Exception as reason:
            self.config[key] = old
            try: self.register_hotkeys()
            except RuntimeError: pass
            self.status.setText(str(reason))
        self.shortcut_buttons[key].setText(shortcut_label(self.config[key]))
    def register_hotkeys(self):
        if self.smoke: return
        from winutil import HotKeys
        if self.hotkeys: self.hotkeys.close(); self.hotkeys = None
        self.hotkeys = HotKeys({1: (self.config['composer_key'], lambda: self.post(self.show_composer)),
            2: (self.config['stt_key'], lambda: self.post(self.toggle_stt))})

    def make_tts(self):
        layout = card(self.tts_layout)
        self.tts_enabled = CheckBox('TTS 사용'); self.tts_enabled.setChecked(self.config['tts_enabled'])
        self.tts_enabled.setLayoutDirection(Qt.LayoutDirection.RightToLeft); layout.addWidget(self.tts_enabled); layout.addWidget(divider())
        self.tts_enabled.toggled.connect(self.toggle_tts_changed)
        self.shortcut_row(layout, '입력 단축키', 'composer_key')
        self.option(layout, '사양', 'tts', list(TTS_MODELS), self.refresh_voices)
        self.voice_row = QWidget(); voice_layout = row(); self.voice_row.setLayout(voice_layout)
        caption = label('목소리'); caption.setMinimumWidth(64); voice_layout.addWidget(caption)
        self.voice_box = QComboBox(); self.voice_box.setMinimumWidth(180); voice_layout.addWidget(self.voice_box, 1); layout.addWidget(self.voice_row)
        self.voice_box.currentIndexChanged.connect(self.voice_changed)
        language_row = row(); caption = label('언어'); caption.setMinimumWidth(64); language_row.addWidget(caption)
        self.language_box = QComboBox(); self.language_box.setMinimumWidth(205); language_row.addWidget(self.language_box, 1); layout.addLayout(language_row)
        self.language_box.currentIndexChanged.connect(self.language_changed)
        self.refresh_voices(); self.scale(layout, '음량', 'volume')
        self.scale(layout, '피치', 'pitch', minimum=-12, maximum=12, factor=1, suffix='')
        self.scale(layout, '속도', 'speed', minimum=50, maximum=200, factor=100, suffix='%')
        reset = button('기본값 복원', self.reset_voice_controls); layout.addWidget(reset, alignment=Qt.AlignmentFlag.AlignRight)
        self.voice_monitoring = self.check(layout, '목소리 모니터링', 'voice_monitoring')
        self.voice_monitoring.setToolTip('전송하는 TTS 목소리를 기본 스피커·헤드폰에서도 함께 듣습니다.')
        self.voice_monitoring.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.surface_controls(card(self.tts_layout), '입력창 모양', 'window')

    def show_setup(self):
        dialog = QDialog(self.root); dialog.setObjectName('main'); dialog.setWindowTitle(CONTRACT['onboarding']['title']); dialog.setFixedWidth(460)
        layout = column(dialog, 24, 16)
        title = label(CONTRACT['onboarding']['title'], heading=True); title.setStyleSheet('font-size: 18px; font-weight: 600;'); layout.addWidget(title)
        for item in CONTRACT['onboarding']['sections']:
            section = column(spacing=10); section.addWidget(label(item['title'], heading=True)); section.addWidget(label(item['text'])); layout.addLayout(section)
        def done():
            self.config['setup_completed'] = True; self.save(); dialog.accept()
        line = row(); line.addStretch(); start = button(CONTRACT['onboarding']['button'], done)
        start.setStyleSheet('QPushButton { background: #087cff; color: white; font-weight: 600; padding: 5px 14px; } QPushButton:hover { background: #006ae0; }')
        start.setDefault(True); line.addWidget(start); layout.addLayout(line)
        dialog.adjustSize(); dialog.setFixedHeight(dialog.sizeHint().height())
        if self.smoke:
            def snapshot():
                dialog.grab().save(str(DATA / 'ui/setup.png')); dialog.reject()
            QTimer.singleShot(300, snapshot)
        dialog.exec()

    def check_microphone(self):
        if self.tts_busy or self.voice_busy or self.capture:
            self.status.setText('음성 작업이 끝난 뒤 연결을 확인하세요.'); return
        dialog = QDialog(self.root); dialog.setObjectName('main'); dialog.setWindowTitle('가상 마이크 연결 점검'); dialog.setMinimumWidth(520)
        layout = column(dialog, 20)
        layout.addWidget(label('가상 마이크 연결 점검', heading=True))
        message = label('장치 확인 중…'); layout.addWidget(message)
        controls = []
        def finished(result):
            message.setText(result['message'])
            for control in controls: control.setEnabled(True)
        def run_check(signal=False, repair=False):
            for control in controls: control.setEnabled(False)
            message.setText('케이블 테스트 중…' if signal else '케이블 확인 중…')
            def work():
                try:
                    from setup_check import inspect, signal_test
                    result = signal_test() if signal else inspect(repair)
                except Exception as error: result = {'ok': False, 'message': str(error)}
                self.post(finished, result)
            threading.Thread(target=work, daemon=True).start()
        line = row()
        for title, action in [('다시 확인', lambda: run_check()), ('케이블 음량 복구', lambda: run_check(repair=True)),
                              ('신호 테스트', lambda: run_check(signal=True))]:
            control = button(title, action); controls.append(control); line.addWidget(control)
        layout.addLayout(line)
        layout.addWidget(label('신호 테스트를 누르면 가상 마이크로 1초 테스트음이 전송됩니다. 통화 밖에서 실행하세요.', muted=True))
        line = row()
        def install_driver():
            import ctypes
            base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent / 'build/bundle'
            installer = base / 'VB-CABLE/VBCABLE_Setup_x64.exe'
            if not installer.is_file(): message.setText('STTS 설치 EXE를 다시 실행해 가상 마이크를 설치하세요.'); return
            from ctypes import wintypes
            execute = ctypes.windll.shell32.ShellExecuteW
            execute.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
            execute.restype = ctypes.c_void_p
            result = execute(None, 'runas', str(installer), None, str(installer.parent), 1) or 0
            message.setText('드라이버 설치 창에서 Install Driver를 누르고 PC를 재시작하세요.' if result > 32 else '설치를 시작하지 못했습니다. 관리자 권한 승인이 필요합니다.')
        line.addWidget(button('가상 마이크 설치', install_driver))
        line.addWidget(button('Windows 소리 설정', lambda: os.startfile('ms-settings:sound')))
        line.addWidget(button('마이크 권한', lambda: os.startfile('ms-settings:privacy-microphone'))); layout.addLayout(line)
        line = row(); line.addStretch(); line.addWidget(button('닫기', dialog.accept)); layout.addLayout(line)
        run_check()
        if self.smoke:
            def snapshot():
                dialog.grab().save(str(DATA / 'ui/connection.png')); dialog.reject()
            QTimer.singleShot(1000, snapshot)
        dialog.exec()

    def refresh_voices(self):
        tier = self.config['tts']; self.voice_box.blockSignals(True); self.voice_box.clear()
        model = TTS_MODELS[tier]
        presets = CONTRACT['voices']['qwen' if model.startswith('qwen') else model]
        for name in presets: self.voice_box.addItem(name, 'preset:' + name)
        if tier in ('중간', '높음'):
            for profile in self.profiles:
                self.voice_box.addItem(profile['name'] or '이름·대본 필요', 'clone:' + profile['id'])
                self.voice_box.model().item(self.voice_box.count() - 1).setEnabled(voice_ready(profile, self.voice_root))
        selected = 'clone:' + self.config['selected_clone_id'] if tier in ('중간', '높음') and self.config.get('selected_clone_id') else 'preset:' + self.config['voice']
        index = self.voice_box.findData(selected)
        if index < 0 and presets: index = 0; self.config['voice'] = presets[0]
        self.voice_box.setCurrentIndex(index); self.voice_box.blockSignals(False); self.voice_row.setVisible(tier != '기본')
        self.refresh_languages(); self.save()
    def voice_changed(self, index):
        value = self.voice_box.itemData(index)
        if not value: return
        if value.startswith('clone:'): self.config['selected_clone_id'] = value.removeprefix('clone:')
        else: self.config['selected_clone_id'] = None; self.config['voice'] = value.removeprefix('preset:')
        self.save()
    def refresh_languages(self):
        key = {'기본': 'gtts', '낮음': 'supertonic3'}.get(self.config['tts'], 'qwenTTS')
        codes = SPEECH_LANGUAGES[key]; self.language_box.blockSignals(True); self.language_box.clear()
        ordered = [code for code in CONTRACT['language_order'] if code in codes]
        ordered += sorted(code for code in codes if code not in ordered)
        for code in ordered:
            self.language_box.addItem(f"{CONTRACT['language_labels'].get(code, code)} · {code}", code)
        current = self.config['language']
        if current not in codes:
            self.config['language'] = next((code for code in ordered if code.split('-')[0] == current.split('-')[0]), 'ko')
        self.language_box.setCurrentIndex(self.language_box.findData(self.config['language'])); self.language_box.blockSignals(False)
    def language_changed(self, index):
        self.config['language'] = self.language_box.itemData(index); self.save()

    def surface_controls(self, layout, title, prefix):
        layout.addWidget(label(title, heading=True))
        colors = row(); colors.addStretch()
        for text, suffix in [('배경', 'bg'), ('글자', 'color')]:
            key = prefix + '_' + suffix
            colors.addWidget(label(text)); control = ColorWell(lambda key=key: self.pick_color(key)); control.setAccessibleName(text + ' 색상')
            self.color_buttons[key] = control; colors.addWidget(control)
        colors.addStretch(); layout.addLayout(colors)
        self.scale(layout, '불투명도', prefix + '_alpha', self.refresh_surfaces)
        if prefix == 'caption': self.scale(layout, '글자 크기', 'caption_font', self.refresh_surfaces, minimum=14, maximum=40, factor=1, suffix='')
        preview = QLabel('음성 입력창 미리보기' if prefix == 'window' else '자막 미리보기')
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter); preview.setMinimumHeight(44 if prefix == 'window' else 56)
        setattr(self, prefix + '_preview', preview); layout.addWidget(preview); self.refresh_surfaces()
    def rgba(self, prefix):
        color = QColor(self.config[prefix + '_bg'])
        return f'rgba({color.red()}, {color.green()}, {color.blue()}, {round(self.config[prefix + "_alpha"] * 255)})'
    def refresh_surfaces(self):
        for key, control in getattr(self, 'color_buttons', {}).items():
            control.set_color(self.config[key])
        for prefix in ('window', 'caption'):
            preview = getattr(self, prefix + '_preview', None)
            if preview:
                preview.setStyleSheet(f'background: {self.rgba(prefix)}; color: {self.config[prefix + "_color"]}; border-radius: 8px; font-size: {13 if prefix == "window" else int(self.config["caption_font"])}px;')
        if self.composer:
            choices = self.composer.findChild(QListWidget)
            if choices: choices.setStyleSheet(f"QListWidget {{ background: transparent; color: {self.config['window_color']}; border: none; padding: 0; font-size: 13px; outline: none; }} QListWidget::item:selected {{ background: rgba(49,130,246,45); color: {self.config['window_color']}; border-radius: 6px; }}")
            self.composer.background = QColor(self.config['window_bg'])
            self.composer.background.setAlphaF(self.config['window_alpha'])
            self.composer.setStyleSheet(f'QLineEdit {{background: transparent; border: none; color: {self.config["window_color"]}; font-size: 16px; padding: 0;}}')
            self.composer.update()
        self.style_caption()
    def pick_color(self, key):
        color = QColorDialog.getColor(QColor(self.config[key]), self.root)
        if color.isValid(): self.config[key] = color.name(); self.save(); self.refresh_surfaces()

    def toggle_tts_changed(self, enabled):
        self.config['tts_enabled'] = enabled; self.save()
        if not enabled: self.cancel_tts(); self.hide_composer()
        self.update_busy()
    def submit(self, widget):
        if getattr(widget, 'preedit', False): return
        input_text = unicodedata.normalize('NFC', widget.text().strip())
        phrases = self.config.get('tts_phrases', {})
        text = phrases.get(input_text, input_text)
        if not self.tts_enabled.isChecked(): self.status.setText('TTS를 켜세요.'); return
        if self.tts_busy or self.voice_busy: self.status.setText('현재 음성 작업이 끝난 후 다시 전송하세요.'); return
        if not 1 <= len(text) <= CONTRACT['limits']['text']: self.status.setText('1~500자를 입력하세요.'); return
        if input_text not in phrases:
            try: clip = self.soundboard.clip_for_input(input_text)
            except ValueError as error:
                self.status.setText(str(error))
                QToolTip.showText(widget.mapToGlobal(QPoint(0, widget.height() + 10)), str(error), widget, msecShowTime=10000)
                return
            else:
                if clip is not None:
                    if self.play_sound(clip): widget.clear(); self.hide_composer()
                    else: QToolTip.showText(widget.mapToGlobal(QPoint(0, widget.height() + 10)), self.status.text(), widget, msecShowTime=10000)
                    return
        from audio import cable_output
        try: cable_output(refresh=True)
        except Exception as error:
            self.status.setText(str(error))
            QToolTip.showText(widget.mapToGlobal(QPoint(0, widget.height() + 10)), str(error), widget, msecShowTime=10000)
            return
        request = {'action': 'tts', 'text': text, 'root': str(self.model_root), 'language': self.config['language'], 'voice': self.config['voice'], 'pitch': self.config.get('pitch', 0), 'speed': self.config.get('speed', 1)}
        model = TTS_MODELS[self.config['tts']]
        profile = next((p for p in self.profiles if p['id'] == self.config.get('selected_clone_id')), None) if model.startswith('qwen') else None
        if profile and not voice_ready(profile, self.voice_root):
            self.status.setText('하단 보이스 클론에서 선택한 목소리의 이름과 대본을 확인해 주세요.'); return
        if model.startswith('qwen'):
            if profile: request.update(reference=str(self.voice_root / (profile['id'] + '.wav')), transcript=profile['transcript'], voice_root=str(self.voice_root))
            else: model += 'Custom'
        request['model'] = model; widget.clear(); self.hide_composer(); self.tts_busy = True
        self.audio_stop = threading.Event(); token = self.audio_stop; worker = self.tts_worker
        monitoring = self.config['voice_monitoring']
        self.status.setText('음성 생성 중…'); self.update_busy()
        def run():
            try:
                import numpy as np
                from audio import play_cable
                result = worker.request(request)
                warning = ''
                if not token.is_set():
                    self.report('가상 마이크로 보내는 중…', active=lambda: self.audio_stop is token and not token.is_set())
                    warning = play_cable(np.frombuffer(base64.b64decode(result['audio']), dtype='<f4'), result['rate'], lambda: self.config['volume'], token, monitor=monitoring)
                self.post(self.finish_tts, token, warning or '')
            except Exception as error:
                if not token.is_set(): self.post(self.finish_tts, token, str(error))
        threading.Thread(target=run, daemon=True).start()
    def finish_tts(self, token, message):
        if token is not self.audio_stop or token.is_set(): return
        self.playing_sound = None
        self.tts_busy = False; self.status.setText(message); self.update_busy()
        worker = self.tts_worker
        def release():
            if self.closing or self.tts_busy or self.audio_stop is not token or self.tts_worker is not worker: return
            worker.stop(); self.tts_worker = self.make_tts_worker()
        QTimer.singleShot(30000, release)
    def cancel_tts(self):
        self.audio_stop.set(); self.tts_worker.stop(); self.tts_worker = self.make_tts_worker()
        self.playing_sound = None
        self.tts_busy = False; self.status.clear(); self.update_busy()

    def show_composer(self):
        if not self.tts_enabled.isChecked(): return
        if self.composer: self.hide_composer(); return
        from winutil import user32
        self.previous_window = user32.GetForegroundWindow()
        window = ComposerWindow()
        layout = column(window, spacing=0); layout.setContentsMargins(12, 10, 12, 10)
        field = ComposerEdit(); field.setFixedHeight(24); field.setPlaceholderText('입력 후 Enter'); layout.addWidget(field)
        choices = QListWidget(); choices.setFocusPolicy(Qt.FocusPolicy.NoFocus); choices.hide(); layout.addWidget(choices)
        field.submitted.connect(lambda: self.submit(field)); field.dismissed.connect(self.hide_composer)
        point = QCursor.pos(); screen = QApplication.screenAt(point) or QApplication.primaryScreen(); area = screen.availableGeometry()
        width, height = min(480, area.width() - 16), 44
        x = min(max(point.x() + 14, area.left() + 8), area.right() - width - 7)
        y = min(max(point.y() + 14, area.top() + 8), area.bottom() - height - 7)
        window.setGeometry(x, y, width, height); self.composer = window; self.refresh_surfaces()
        window.show(); window.raise_(); window.activateWindow(); field.setFocus()
        def fill_completion():
            item = choices.currentItem()
            if item is not None: field.setText(item.data(Qt.ItemDataRole.UserRole)); field.end(False); field.setFocus()
        def update_completions():
            from interaction import completion_candidates
            items = [] if field.preedit else completion_candidates(field.text(), self.config.get('tts_phrases', {}), [clip['name'] for clip in self.soundboard.clips])
            choices.clear()
            for name, kind in items:
                item = QListWidgetItem(name + '  ·  ' + kind); item.setData(Qt.ItemDataRole.UserRole, name); item.setSizeHint(QSize(0, 32)); choices.addItem(item)
            choices.setVisible(bool(items)); field.has_completions = bool(items)
            extra = len(items) * 32 + 8 if items else 0
            choices.setFixedHeight(extra); choices.setCurrentRow(0 if items else -1)
            window.setGeometry(x, max(area.top() + 8, min(y, area.bottom() - height - extra - 7)), width, height + extra)
        field.textChanged.connect(update_completions); field.compositionChanged.connect(update_completions)
        field.navigated.connect(lambda step: choices.setCurrentRow((choices.currentRow() + step) % choices.count()) if choices.count() else None)
        field.completed.connect(fill_completion); choices.itemClicked.connect(lambda _: fill_completion())
        self.composer_opened = time.monotonic(); self.mouse_points = []; self.composer_timer.start(20)
    def composer_tick(self):
        if not self.composer: return
        from winutil import user32, root_handle
        now = time.monotonic()
        if self.config['outside'] and now - self.composer_opened > .5 and user32.GetForegroundWindow() != root_handle(self.composer) and user32.GetAsyncKeyState(1) & 0x8000:
            self.hide_composer(restore_focus=False); return
        point = QCursor.pos(); self.mouse_points.append((now, point.x(), point.y()))
        self.mouse_points = [p for p in self.mouse_points if now - p[0] < .65]
        if self.config['shake']:
            from interaction import mouse_shaken
            if mouse_shaken(self.mouse_points, self.config['shake_sensitivity']): self.hide_composer()
    def hide_composer(self, restore_focus=True):
        self.composer_timer.stop()
        if self.composer: self.composer.close(); self.composer.deleteLater(); self.composer = None
        if restore_focus and getattr(self, 'previous_window', None):
            from winutil import user32
            user32.SetForegroundWindow(self.previous_window)
        self.previous_window = None

    def make_stt(self):
        layout = card(self.stt_layout)
        self.stt_enabled = CheckBox('STT 사용'); self.stt_enabled.setLayoutDirection(Qt.LayoutDirection.RightToLeft); self.stt_enabled.clicked.connect(self.toggle_stt); layout.addWidget(self.stt_enabled); layout.addWidget(divider())
        self.shortcut_row(layout, '자막 단축키', 'stt_key')
        self.option(layout, '사양', 'stt', list(STT_MODELS), self.stt_model_changed)
        self.history = QLabel(); self.history.setWordWrap(True); self.history.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.history.hide(); layout.addWidget(self.history)
        self.surface_controls(card(self.stt_layout), '자막 모양', 'caption')
    def stt_model_changed(self):
        if self.capture: self.stop_stt(); self.toggle_stt()
    def toggle_stt(self):
        if self.capture: self.stop_stt(); return
        if self.voice_busy: self.stt_enabled.setChecked(False); self.status.setText('목소리 저장이 끝난 뒤 STT를 켜세요.'); return
        from audio import Capture, Worker
        def progress(message): self.report(message, active=lambda: self.capture is capture)
        def caption(text): self.post(lambda: self.show_caption(text) if self.capture is capture else None)
        capture = Capture(self.job, Worker(self.job, progress), STT_MODELS[self.config['stt']], self.model_root,
                          caption, progress, lambda: self.post(self.capture_ended, capture))
        try: capture.start()
        except Exception as error: capture.stop(); self.stt_enabled.setChecked(False); self.status.setText(str(error)); return
        self.capture = capture; self.stt_enabled.setChecked(True); self.show_caption(''); self.status.setText('STT 준비 중…'); self.update_busy()
    def capture_ended(self, capture):
        if self.capture is capture: self.stop_stt()
    def stop_stt(self):
        capture, self.capture = self.capture, None
        if capture: capture.stop()
        self.caption_timer.stop()
        if self.caption: self.caption.close(); self.caption.deleteLater(); self.caption = None
        self.stt_enabled.setChecked(False); self.update_busy()
    def show_caption(self, text):
        if not self.capture: return
        if text:
            self.caption_history = (self.caption_history + [text])[-CONTRACT['caption']['history']:]
            self.history.setText('\n\n'.join(self.caption_history)); self.history.show()
            self.history.setStyleSheet(f'background: {self.rgba("caption")}; color: {self.config["caption_color"]}; border-radius: 8px; padding: 12px;')
        if not self.caption:
            self.caption = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
            self.caption.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground); self.caption.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            layout = column(self.caption, 0, 0); self.caption_label = QLabel(); self.caption_label.setWordWrap(True)
            self.caption_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter); layout.addWidget(self.caption_label)
            self.caption.show()
            from winutil import clickthrough
            clickthrough(self.caption)
        self.caption_label.setText('\n'.join(self.caption_history[-CONTRACT['caption']['visible']:]) if text else '')
        self.style_caption(); self.caption.show(); self.caption_timer.start(CONTRACT['caption']['expiry_seconds'] * 1000)
    def clear_caption(self):
        if self.caption: self.caption_label.clear(); self.style_caption()
    def style_caption(self):
        if not self.caption: return
        screen = self.root.screen() or QApplication.primaryScreen(); area = screen.availableGeometry()
        width = min(CONTRACT['caption']['width'], area.width() - 40)
        self.caption_label.setStyleSheet(f'background: {self.rgba("caption")}; color: {self.config["caption_color"]}; font-size: {int(self.config["caption_font"])}px; font-weight: 500; border-radius: 10px; padding: 14px;')
        self.caption.setFixedWidth(width); self.caption_label.setFixedWidth(width)
        height = max(56, self.caption_label.heightForWidth(width), self.caption_label.sizeHint().height())
        height = min(height, area.height() - 40)
        self.caption.setFixedHeight(height)
        self.caption.move(area.left() + (area.width() - width) // 2, max(area.top() + 20, area.bottom() - int(self.config['caption_y']) - height))

    def select_tab(self, index):
        if self.recording_key: self.finish_shortcut()
        if self.voice_cancel: self.voice_cancel()
        self.tools.dismiss()
        self.tabs.setCurrentIndex(index); self.tab_buttons.button(index).setChecked(True); self.footer.setVisible(index == 0); self.layout_overlays()
    def save_tts_phrase(self, shortcut, phrase, original=None):
        if getattr(self, 'voice_busy', False): raise ValueError('파일 가져오기가 끝난 뒤 단축어를 저장해 주세요.')
        shortcut, phrase = unicodedata.normalize('NFC', shortcut.strip()), phrase.strip()
        if not 1 <= len(shortcut) <= CONTRACT['limits']['text'] or not 1 <= len(phrase) <= CONTRACT['limits']['text']: raise ValueError('단축어와 읽을 문장은 각각 1~500자로 입력해 주세요.')
        phrases = dict(self.config.get('tts_phrases', {}))
        if any(key != original and unicodedata.normalize('NFC', key.strip()) == shortcut for key in phrases): raise ValueError('이미 저장된 단축어입니다. 기존 항목을 수정해 주세요.')
        if any(unicodedata.normalize('NFC', clip['name'].strip()) == shortcut for clip in self.soundboard.clips): raise ValueError('같은 이름의 사운드가 있습니다. 다른 단축어를 입력해 주세요.')
        if original is not None: phrases.pop(original, None)
        phrases[shortcut] = phrase
        write_json(DATA / 'settings.json', dict(self.config, tts_phrases=phrases))
        self.config['tts_phrases'] = phrases
    def delete_tts_phrase(self, shortcut):
        phrases = dict(self.config.get('tts_phrases', {})); phrases.pop(shortcut, None)
        write_json(DATA / 'settings.json', dict(self.config, tts_phrases=phrases))
        self.config['tts_phrases'] = phrases

    def add_sound_files(self):
        if self.tts_busy or self.voice_busy: self.status.setText('현재 음성 작업이 끝난 뒤 파일을 추가하세요.'); return
        paths, _ = QFileDialog.getOpenFileNames(self.root, '사운드 추가', '', '음성 파일 (*.wav *.mp3 *.m4a *.aiff *.aif *.flac)')
        if not paths: return
        self.voice_busy = True; self.update_busy(); self.status.setText('사운드 가져오는 중…')
        def run():
            from audio import Worker
            import numpy as np
            worker = Worker(self.job, self.report); errors = []
            try:
                for path in paths:
                    try:
                        result = worker.request({'action': 'decode_sound', 'path': path})
                        samples = np.frombuffer(base64.b64decode(result['audio']), dtype='<f4')
                        self.soundboard.import_samples(Path(path).stem, samples, 24000, self.config.get('tts_phrases', {}))
                    except Exception as error: errors.append(Path(path).name + ': ' + str(error))
            finally: worker.stop()
            self.post(self.finish_sound_import, errors)
        threading.Thread(target=run, daemon=True).start()

    def finish_sound_import(self, errors):
        self.voice_busy = False; self.update_busy(); self.status.setText('\n'.join(errors))
        if self.tools.active == 'soundboard': self.tools.show_sounds()

    def delete_sound(self, clip):
        if self.tts_busy or self.voice_busy: return
        if QMessageBox.question(self.root, '사운드를 삭제할까요?', clip['name'] + ' 등록을 삭제합니다. 가져온 원본 파일은 유지됩니다.') != QMessageBox.StandardButton.Yes: return
        try: self.soundboard.remove(clip)
        except (OSError, ValueError) as error: self.status.setText(str(error)); return
        self.tools.show_sounds()

    def play_sound(self, clip):
        if not self.tts_enabled.isChecked(): self.status.setText('TTS 사용을 켜 주세요.'); return False
        if self.tts_busy or self.voice_busy: self.status.setText('현재 음성 작업이 끝난 뒤 재생해 주세요.'); return False
        from audio import cable_output, play_cable
        try: cable_output(refresh=True)
        except Exception as error: self.status.setText(str(error)); return False
        self.audio_stop = threading.Event(); token = self.audio_stop
        self.tts_busy = True; self.playing_sound = clip['id']; self.update_busy(); self.status.setText(clip['name'] + ' 재생 중…')
        monitoring = self.config['voice_monitoring']; pitch = self.config.get('pitch', 0); speed = self.config.get('speed', 1); worker = self.tts_worker if pitch or speed != 1 else None
        def run():
            try:
                import soundfile as sf
                if pitch or speed != 1:
                    result = worker.request({'action': 'decode_sound', 'path': str(self.soundboard.audio_path(clip)), 'pitch': pitch, 'speed': speed})
                    import numpy as np
                    samples, rate = np.frombuffer(base64.b64decode(result['audio']), dtype='<f4'), result['rate']
                else: samples, rate = sf.read(self.soundboard.audio_path(clip), dtype='float32')
                warning = play_cable(samples, rate, lambda: self.config['volume'], token, monitor=monitoring) if not token.is_set() else None
                self.post(self.finish_tts, token, warning or '')
            except Exception as error:
                if not token.is_set(): self.post(self.finish_tts, token, str(error))
        threading.Thread(target=run, daemon=True).start()
        return True

    def save_profiles(self): write_json(self.voice_root / 'profiles.json', self.profiles); self.refresh_voices()
    def delete_voice(self, profile):
        if self.tts_busy or self.voice_busy: self.status.setText('음성 작업이 끝난 뒤 삭제하세요.'); return
        if QMessageBox.question(self.root, '목소리 삭제', f"{profile['name']} 목소리를 삭제할까요?") != QMessageBox.StandardButton.Yes: return
        from send2trash import send2trash
        path = self.voice_root / (profile['id'] + '.wav')
        if path.exists(): send2trash(str(path))
        self.profiles.remove(profile); self.save_profiles(); self.tools.show_voices()
    def add_voice_files(self):
        if self.tts_busy or self.voice_busy or self.capture: self.status.setText('TTS와 STT를 멈춘 뒤 목소리를 추가하세요.'); return
        paths, _ = QFileDialog.getOpenFileNames(self.root, '목소리 추가', '', '음성 파일 (*.mp3 *.wav *.m4a *.aiff *.aif)')
        if not paths: return
        self.voice_busy = True; self.update_busy()
        def run():
            for index, path in enumerate(paths): self.store_voice((Path(path).stem, ''), None, path, more=index < len(paths) - 1)
        threading.Thread(target=run, daemon=True).start()
    def store_voice(self, details, data, path, more=False):
        from audio import Worker
        import numpy as np
        import soundfile as sf
        from scipy.signal import resample_poly
        worker = Worker(self.job, self.report)
        profile = None
        try:
            name, transcript = details
            if path:
                result = worker.request({'action': 'decode', 'path': path}); data = np.frombuffer(base64.b64decode(result['audio']), dtype='<f4')
            if not CONTRACT['limits']['recording_min'] <= len(data) / 24000 <= CONTRACT['limits']['recording_max'] or not np.isfinite(data).all() or np.max(np.abs(data)) <= CONTRACT['limits']['voice_peak']:
                raise ValueError('목소리가 들리는 3~30초 샘플이 필요합니다.')
            ident = uuid.uuid4().hex
            sf.write(self.voice_root / (ident + '.wav'), data, 24000, subtype='PCM_16')
            profile = {'id': ident, 'name': name, 'transcript': transcript, 'source_name': Path(path).name if path else '마이크 녹음.wav'}
            self.post(self.register_voice, profile)
            if not transcript:
                self.report('받아쓰는 중…'); pcm = resample_poly(data, 2, 3).astype('<f4')
                result = worker.request({'action': 'stt', 'model': 'turbo', 'root': str(self.model_root), 'audio': base64.b64encode(pcm.tobytes()).decode()})
                transcript = result['text'].strip()
                if not 1 <= len(transcript) <= CONTRACT['limits']['transcript']: raise ValueError('대본을 인식하지 못했습니다. 직접 입력해 주세요.')
                profile['transcript'] = transcript
            self.post(self.finish_voice, profile, None, more)
        except Exception as error:
            # Keep an imported recording when transcription fails; it can be edited or retried.
            self.post(self.finish_voice, profile, str(error), more)
        finally: worker.stop()

    def transcribe_voice(self, profile):
        if self.tts_busy or self.voice_busy or self.capture:
            self.status.setText('음성·자막 작업이 끝난 뒤 대본을 입력하세요.'); return
        from audio import Worker
        cancelled = threading.Event(); worker = Worker(self.job, lambda message: self.report(message) if not cancelled.is_set() else None)
        self.voice_busy = True; self.update_busy(); self.tools.set_voice_transcribing(True)
        def cancel():
            cancelled.set(); worker.stop(); self.voice_cancel = None
            self.voice_busy = False; self.update_busy(); self.tools.set_voice_transcribing(False)
        self.voice_cancel = cancel
        def finish(text, error):
            if cancelled.is_set(): return
            self.voice_cancel = None; self.voice_busy = False; self.update_busy()
            if error:
                self.tools.set_voice_transcribing(False); self.status.setText(error); return
            profile['transcript'] = text; self.save_profiles(); self.tools.edit_voice(profile)
        def run():
            try:
                import numpy as np
                from scipy.signal import resample_poly
                decoded = worker.request({'action': 'decode', 'path': str(self.voice_root / (profile['id'] + '.wav'))})
                pcm = resample_poly(np.frombuffer(base64.b64decode(decoded['audio']), dtype='<f4'), 2, 3).astype('<f4')
                result = worker.request({'action': 'stt', 'model': 'turbo', 'root': str(self.model_root), 'audio': base64.b64encode(pcm.tobytes()).decode()})
                text = result['text'].strip()
                if not 1 <= len(text) <= CONTRACT['limits']['transcript']: raise ValueError('대본을 인식하지 못했습니다. 직접 입력해 주세요.')
                self.post(finish, text, '')
            except Exception as error:
                self.post(finish, '', str(error))
            finally: worker.stop()
        threading.Thread(target=run, daemon=True).start()

    def register_voice(self, profile):
        name, number = profile['name'], 2
        while any(p['name'] == profile['name'] for p in self.profiles):
            profile['name'] = f'{name} ({number})'; number += 1
        self.profiles.append(profile); self.save_profiles()

    def finish_voice(self, profile, error, more=False):
        self.voice_busy = more; self.update_busy()
        if profile is None:
            self.status.setText(error)
            if not more and self.tools.active == "voice": self.tools.show_voices()
            return
        self.save_profiles(); self.status.setText(error or '')
        if not more and self.tools.active == "voice": self.tools.edit_voice(profile)

    def delete_model(self, path):
        if self.tts_busy or self.capture or self.voice_busy: self.status.setText('음성 작업을 모두 멈춘 뒤 삭제하세요.'); return
        if path.parent != self.model_root or path.is_symlink(): return
        if QMessageBox.question(self.root, '모델을 삭제할까요?', f'{path.name}\n다음 사용 시 다시 다운로드합니다.') != QMessageBox.StandardButton.Yes: return
        self.cancel_tts(); shutil.rmtree(path); self.settings.show_models()
    def update_busy(self):
        enabled = self.tts_enabled.isChecked() and not (self.tts_busy or self.voice_busy)
        self.boxes['tts'].setEnabled(enabled); self.voice_box.setEnabled(enabled); self.language_box.setEnabled(enabled)
        self.voice_monitoring.setEnabled(enabled)
        for key in ('pitch', 'speed'): self.voice_sliders[key].setEnabled(not self.tts_busy)
        self.boxes['stt'].setEnabled(not (self.capture or self.voice_busy)); self.tts_cancel.setVisible(self.tts_busy); self.status.dismiss.setVisible(not self.tts_busy); self.status.fit_content(); self.layout_overlays()
        self.tools.update_sound_controls()
    @property
    def overlay_bottom(self):
        return (60 if self.tabs.currentIndex() == 0 else 0) + (44 if self.status.text() else 0)

    def layout_overlays(self):
        self.footer.move((self.root.width() - self.footer.width()) // 2, self.root.height() - 52)
        self.status_slot.setFixedSize(self.status.width() + 48, 44)
        self.status_slot.move((self.root.width() - self.status_slot.width()) // 2, self.root.height() - self.overlay_bottom)
        padding = CONTRACT['window']['padding']
        for index, layout in enumerate((self.tts_layout, self.stt_layout, self.settings_layout)):
            layout.setContentsMargins(padding, padding + 60, padding, padding + (60 if index == 0 else 0) + (44 if self.status.text() else 0))
        if hasattr(self, 'tools'): self.tools.panel.resize(self.content.width() - 24, self.content.height() - 88 - self.overlay_bottom)
        self.navigation.raise_(); self.footer.raise_(); self.status_slot.raise_()

    def make_tray(self):
        self.tray = QSystemTrayIcon(icon_for('TTS 단축어'), self.root); self.tray.setToolTip('STTS'); menu = QMenu()
        for title, callback in [('STTS 열기', self.show), ('입력창 열기', self.show_composer), ('자막 중지', self.stop_stt), ('종료', self.quit)]: menu.addAction(title).triggered.connect(callback)
        self.tray.setContextMenu(menu); self.tray.activated.connect(lambda reason: self.show() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show(); self.tray_menu = menu
    def show(self): self.root.showNormal(); self.root.raise_(); self.root.activateWindow()
    def close_window(self):
        self.tools.dismiss(animated=False)
        if self.recording_key: self.finish_shortcut()
        if self.voice_cancel: self.voice_cancel()
        if self.config['close'] == '앱 종료': self.quit()
        elif self.config['close'] == '최소화': self.root.showMinimized()
        else: self.root.hide()
    def quit(self):
        if self.closing: return
        if self.recording_key: self.finish_shortcut()
        if self.voice_cancel: self.voice_cancel()
        self.closing = True; self.save(); self.audio_stop.set()
        if self.capture: self.capture.stop()
        self.tts_worker.stop()
        if self.hotkeys: self.hotkeys.close()
        if self.tray: self.tray.hide()
        self.job.close(); self.root.close(); QApplication.instance().quit()


def main():
    global DATA
    if '--verify-install' in sys.argv:
        import contextlib, traceback
        from verify_flow import main as verify
        DATA.mkdir(parents=True, exist_ok=True)
        with (DATA / 'verification.log').open('w', encoding='utf-8', buffering=1) as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            try:
                verify(Path(sys.executable).parent, DATA)
            except Exception as error:
                traceback.print_exc(); write_json(DATA / 'flow.json', {'ok': False, 'error': str(error)})
                raise SystemExit(1)
        return
    if '--diagnose-audio' in sys.argv:
        from setup_check import inspect, signal_test
        DATA.mkdir(parents=True, exist_ok=True)
        result = {'version': VERSION, 'ok': False}
        try:
            result.update(signal_test() if '--signal-test' in sys.argv else inspect())
        except Exception as error: result['error'] = str(error)
        write_json(DATA / 'audio-diagnostic.json', result)
        return
    from winutil import SingleInstance, user32
    smoke = '--smoke-test' in sys.argv; temporary = None
    if smoke and 'STTS_DATA_DIR' not in os.environ:
        import tempfile
        temporary = tempfile.TemporaryDirectory(prefix='STTS-smoke-'); DATA = Path(temporary.name)
    singleton = SingleInstance()
    user32.FindWindowW.restype = __import__('ctypes').wintypes.HWND
    if singleton.duplicate and not smoke:
        hwnd = user32.FindWindowW(None, 'STTS')
        if hwnd: user32.ShowWindow(hwnd, 9); user32.SetForegroundWindow(hwnd)
        return
    qt = QApplication(sys.argv); qt.setStyle('Fusion'); qt.setQuitOnLastWindowClosed(False)
    font = QFont('Malgun Gothic', 10); font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias); qt.setFont(font)
    root = MainWindow(); app = App(root, smoke=smoke)
    if smoke:
        title = f'STTS smoke {os.getpid()}'
        root.setWindowTitle(title)
        assert user32.FindWindowW(None, title), 'The background window cannot be found on a second launch.'
        root.setWindowTitle('STTS')
    # Installation opens the window even when an existing user prefers hidden startup.
    if smoke or '--show' in sys.argv or not app.config['background'] or not app.config.get('setup_completed'): app.show()
    if smoke:
        def test_flow():
            try:
                ui = DATA / 'ui'; ui.mkdir(exist_ok=True)
                def screenshot(name): QApplication.processEvents(); assert root.grab().save(str(ui / (name + '.png')))
                assert app.footer.isVisible()
                screenshot('tts')
                navigation_geometry = app.navigation.geometry()
                assert app.content.geometry() == root.rect()
                app.tts_page.verticalScrollBar().setValue(app.tts_page.verticalScrollBar().maximum())
                screenshot('menu-scroll')
                assert app.navigation.geometry() == navigation_geometry
                pixels = root.grab().toImage(); ratio = pixels.devicePixelRatio()
                assert pixels.pixelColor(round(40 * ratio), round(55 * ratio)).name() == '#ffffff'
                app.tts_page.verticalScrollBar().setValue(0)
                screenshot('bottom-menu')
                pixels = root.grab().toImage(); ratio = pixels.devicePixelRatio()
                assert pixels.pixelColor(round(40 * ratio), round(690 * ratio)).name() == '#ffffff'
                content_geometry = app.content.geometry(); footer_geometry = app.footer.geometry()
                app.tts_busy = True; app.status.setText('음성 생성 중…'); app.update_busy(); QApplication.processEvents()
                status_y = app.status_slot.y()
                assert app.status.isVisible() and app.tts_cancel.isVisible() and not app.status.dismiss.isVisible()
                assert app.navigation.geometry() == navigation_geometry
                assert app.content.y() == content_geometry.y() and app.footer.geometry() == footer_geometry
                assert app.content.geometry() == content_geometry
                assert app.tts_layout.contentsMargins().bottom() == CONTRACT['window']['padding'] + 104
                assert app.status_slot.geometry().bottom() < app.footer.y()
                assert app.status.width() < app.content.width() / 2 and app.status.height() == 36
                screenshot('status-pill')
                app.tts_page.verticalScrollBar().setValue(app.tts_page.verticalScrollBar().maximum())
                app.tool_buttons['phrases'].click(); app.tools.animation.setCurrentTime(app.tools.animation.duration())
                screenshot('status-pill-drawer'); assert app.status_slot.y() == status_y
                assert root.childAt(app.status.mapTo(root, app.status.rect().center())) in (app.status, app.status.message, app.tts_cancel)
                app.select_tab(2); QApplication.processEvents(); assert app.status.isVisible() and app.status_slot.geometry().bottom() < root.height()
                app.tts_cancel.click(); QApplication.processEvents(); assert not app.tts_busy and not app.status.isVisible()
                app.select_tab(0); QApplication.processEvents()
                assert app.content.geometry() == content_geometry and app.footer.geometry() == footer_geometry
                app.tts_page.verticalScrollBar().setValue(0)
                app.select_tab(1); assert not app.footer.isVisible(); screenshot('stt'); app.select_tab(2); assert not app.footer.isVisible()
                for name, show in [('settings', app.settings.show_menu), ('input', app.settings.show_input), ('models', app.settings.show_models), ('runtime', app.settings.show_runtime)]: show(); screenshot(name)
                app.select_tab(0); assert app.footer.isVisible()
                for key in ('voice', 'phrases', 'soundboard'):
                    app.tool_buttons[key].click(); assert app.tools.active == key and app.tools.isVisible()
                    app.tools.animation.setCurrentTime(100); assert app.tools.panel.y() > 0; screenshot(key + '-opening')
                    app.tools.animation.setCurrentTime(app.tools.animation.duration()); screenshot(key)
                    app.tools.dismiss(); app.tools.animation.setCurrentTime(app.tools.animation.duration()); assert not app.tools.isVisible()
                app.tool_buttons['voice'].click(); app.select_tab(0)
                app.tools.animation.setCurrentTime(app.tools.animation.duration()); assert not app.tools.isVisible()
                app.select_tab(0); app.show_setup(); app.check_microphone()
                original_background = app.config['window_bg'], app.config['window_alpha']
                app.config.update(window_bg='#1464c8', window_alpha=.6)
                app.show_composer(); assert app.composer.isVisible(); QApplication.processEvents()
                frame = app.composer.grab(); pixels = frame.toImage(); ratio = pixels.devicePixelRatio()
                actual = pixels.pixelColor(round(240 * ratio), round(5 * ratio)).getRgb()
                assert all(abs(value - expected) <= 2 for value, expected in zip(actual, (20, 100, 200, 153))), actual
                assert pixels.pixelColor(0, 0).alpha() == 0
                frame.save(str(ui / 'composer.png'))
                field = app.composer.findChild(ComposerEdit); choices = app.composer.findChild(QListWidget)
                original_phrases = app.config.get('tts_phrases', {})
                app.config['tts_phrases'] = {'자동완성 하나': '하나', '자동완성 둘': '둘'}
                field.setText('자동'); QApplication.processEvents()
                assert choices.count() == 2 and choices.isVisible() and app.composer.height() > 44
                assert app.composer.grab().save(str(ui / 'autocomplete.png'))
                QApplication.sendEvent(field, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier))
                expected = choices.currentItem().data(Qt.ItemDataRole.UserRole)
                QApplication.sendEvent(field, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier))
                assert field.text() == expected and not choices.isVisible() and not app.tts_busy
                field.clear(); QApplication.sendEvent(field, QInputMethodEvent('자', [])); assert field.preedit and not choices.isVisible()
                commit = QInputMethodEvent(); commit.setCommitString('자동'); QApplication.sendEvent(field, commit)
                assert not field.preedit and choices.count() == 2
                app.config['tts_phrases'] = original_phrases
                app.voice_sliders['pitch'].setValue(6); app.voice_sliders['speed'].setValue(150); app.reset_voice_controls()
                assert app.config['pitch'] == 0 and app.config['speed'] == 1 and app.config['volume'] == 1

                app.soundboard.clips = [{'id': 'first', 'name': '__duplicate_sound__'}, {'id': 'second', 'name': '__duplicate_sound__'}]
                field = app.composer.findChild(ComposerEdit); field.setText('__duplicate_sound__'); app.submit(field)
                assert app.composer.isVisible() and field.text() == '__duplicate_sound__'
                assert '같은 이름의 사운드가 여러 개' in app.status.text()
                app.soundboard.clips = []
                app.hide_composer(); app.status.clear()
                app.config['window_bg'], app.config['window_alpha'] = original_background
                root.hide(); app.show(); QApplication.processEvents(); assert root.isVisible() and not root.isMinimized()
                app.capture = type('TestCapture', (), {'stop': lambda self: None})()
                original = app.config['caption_font']; app.config['caption_font'] = 40
                app.show_caption('큰 글자에서도 문장이 잘리지 않고 보이는지 확인합니다. 가상 마이크와 자막을 함께 사용합니다.'); QApplication.processEvents()
                assert app.caption.height() >= app.caption_label.heightForWidth(app.caption_label.width())
                app.caption.grab().save(str(ui / 'caption.png')); app.config['caption_font'] = original; app.stop_stt()
                write_json(DATA / 'gui-smoke.json', {'ok': True, 'version': VERSION})
            finally: app.quit()
        QTimer.singleShot(600, test_flow)
    qt.exec()
    if temporary: temporary.cleanup()


if __name__ == '__main__': main()
