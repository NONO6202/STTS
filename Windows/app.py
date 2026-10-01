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

from config import DEMO, STORE_URL, CONTRACT, VERSION, DEFAULTS, TTS_MODELS, STT_MODELS, SPEECH_LANGUAGES, data_directory, write_json, voice_ready
import theme
from theme import P, TOKENS
from widgets import label, column, row, button, divider, icon_for, icon_button, badge, styled, restyle, section, Bridge, MainWindow, ComposerWindow, ComposerEdit, ShortcutFilter, StatusMessage, CheckBox, ColorWell
from settings import SettingsPanel
from tools_panel import ToolsPanel
from soundboard import SoundboardLibrary
from localization import tr, message as localize_message, language_name, speech_language, system_languages, install_qt_translations

DATA = data_directory()


class NoAchievements:
    def __getattr__(self, name): return lambda *args, **kwargs: None


class App:
    # Defaults for state added after __init__ was split into many tested steps.
    achievements = NoAchievements(); sent_history = (); skipping = None
    def __init__(self, root, smoke=False):
        from winutil import ChildJob
        self.root, self.smoke = root, smoke; root.owner = self
        self.closing = False; self.config = dict(DEFAULTS)
        DATA.mkdir(parents=True, exist_ok=True)
        self.model_root, self.voice_root = DATA / 'Models', DATA / 'Voice'
        self.model_root.mkdir(exist_ok=True); self.voice_root.mkdir(exist_ok=True)
        try: stored_config = json.loads((DATA / 'settings.json').read_text(encoding='utf-8'))
        except (OSError, ValueError): stored_config = {}
        self.config.update(stored_config)
        if self.config['close'] not in CONTRACT['close_actions']: self.config['close'] = '백그라운드 실행'
        self.config['language_follows_system'] = stored_config.get('language_follows_system', 'language' not in stored_config)
        self.config.setdefault('microphone_device', '')
        self.config.setdefault('microphone_volume', 1.0)
        self.config.setdefault('microphone_enabled', False)
        self.config.setdefault('microphone_pitch', 0.0)
        self.config.setdefault('microphone_filter', '기본')
        self.config.setdefault('microphone_strength', 0.65)
        self.config.setdefault('skip_key', None); self.config.setdefault('sound_keys', {}); self.config.setdefault('microphone_presets', [])
        from audio import MicrophonePassthrough
        self.live_microphone = MicrophonePassthrough()
        self.microphone_error = ''
        self.microphone_active = False; self.microphone_retry_at = 0.0
        try: self.profiles = json.loads((self.voice_root / 'profiles.json').read_text(encoding='utf-8'))
        except (OSError, ValueError): self.profiles = []
        if 'selected_clone_id' not in self.config:
            old = next((p for p in self.profiles if '클론 · ' + p['name'] == self.config['voice']), None)
            self.config['selected_clone_id'] = old['id'] if old else None
        self.capture = self.hotkeys = self.composer = self.caption = self.tray = None; self.header_refreshers = []
        self.voice_cancel = None; self.recording_key = None; self.shortcut_buttons = {}; self.boxes = {}; self.color_buttons = {}; self.voice_sliders = {}
        self.tts_busy = self.voice_busy = False; self.audio_stop = threading.Event()
        self.tts_queue = []; self.composer_draft = ""; self.sent_history = []; self.skipping = None
        self.backends = {}; self.caption_history = []
        self.soundboard = SoundboardLibrary(DATA / "Soundboard"); self.playing_sound = None
        from achievements import Achievements
        from steam import library_path
        # Only full Steam builds carry the Steam library; source builds and the demo never contact Steam.
        self.achievements = Achievements(DATA, enabled=not (DEMO or smoke) and library_path().is_file())
        self.job = ChildJob(); self.tts_worker = self.make_tts_worker()
        root.setObjectName('main'); root.setWindowTitle(tr('STTS')); root.setFixedSize(CONTRACT['window']['width'], CONTRACT['window']['height'])
        theme.use(theme.dark_system()); root.setStyleSheet(theme.stylesheet())
        # A second launch must be able to find the window even before it has ever been shown.
        root.winId()
        if not smoke:
            from winutil import blend_title_bar
            theme.on_change(lambda: blend_title_bar(root, P['background']))
        hints = QApplication.styleHints()
        if hasattr(hints, 'colorSchemeChanged'):
            hints.colorSchemeChanged.connect(lambda _: (theme.use(theme.dark_system()), root.setStyleSheet(theme.stylesheet())))
        self.bridge = Bridge(self, root)
        layout = column(root, spacing=0)
        segments = self.navigation = QFrame(root); segments.setObjectName('segments'); segment_layout = QHBoxLayout(segments)
        segment_layout.setContentsMargins(4, 4, 4, 4); segment_layout.setSpacing(4)
        self.tab_buttons = QButtonGroup(root); self.tab_buttons.setExclusive(True)
        for index, title in enumerate(CONTRACT['tabs']):
            control = QPushButton(tr(title)); control.setObjectName('segment'); control.setFixedHeight(30); control.setCheckable(True); control.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            self.tab_buttons.addButton(control, index); segment_layout.addWidget(control, 1)
        self.tab_buttons.idClicked.connect(self.select_tab); self.tab_buttons.button(0).setChecked(True)
        for index, control in enumerate(self.tab_buttons.buttons()): self.tint_on_check(control, CONTRACT['tabs'][index])
        for control in self.tab_buttons.buttons(): control.ensurePolished()
        nav_width = max(control.sizeHint().width() for control in self.tab_buttons.buttons()) * len(CONTRACT['tabs']) + 20
        segments.setFixedSize(min(root.width() - 48, max(CONTRACT['window']['tabs_width'], nav_width)), 38)
        segments.move((root.width() - segments.width()) // 2, 12)
        self.content = QWidget(); content_layout = column(self.content)
        self.tabs = QStackedWidget(); content_layout.addWidget(self.tabs); layout.addWidget(self.content, 1)
        self.status_slot = QWidget(root); status_layout = column(self.status_slot, 0, 0); status_layout.setContentsMargins(24, 0, 24, 8)
        self.status = StatusMessage(self.status_slot); status_layout.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.status_slot.hide()
        self.queue_label = label(''); self.status.layout().addWidget(self.queue_label); self.queue_label.hide()
        self.tts_cancel = button(tr('취소'), self.cancel_tts); self.tts_cancel.setFixedHeight(24); self.status.layout().insertWidget(1, self.tts_cancel); self.tts_cancel.hide()
        self.tts_page, self.tts_layout = self.page(); self.microphone_page, self.microphone_layout = self.page(); self.stt_page, self.stt_layout = self.page(); self.settings_page, self.settings_layout = self.page()
        for page in (self.tts_page, self.microphone_page, self.stt_page, self.settings_page): self.tabs.addWidget(page)
        
        footer_panel = self.footer = QFrame(root); footer_panel.setObjectName('segments'); footer_panel.setFixedSize(CONTRACT['window']['tabs_width'], 38)
        footer_layout = QHBoxLayout(footer_panel); footer_layout.setContentsMargins(4, 4, 4, 4); footer_layout.setSpacing(4)
        self.tool_buttons = {}
        for item in CONTRACT['tools']:
            control = button(tr(item['title']), lambda key=item['id']: self.tools.toggle(key)); control.setObjectName('segment'); control.setCheckable(True); control.setFixedHeight(30); control.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            self.tool_buttons[item['id']] = control; footer_layout.addWidget(control, 1); self.tint_on_check(control, item['title'])
        for control in self.tool_buttons.values(): control.ensurePolished()
        footer_width = max(control.sizeHint().width() for control in self.tool_buttons.values()) * len(self.tool_buttons) + 16
        footer_panel.setFixedWidth(min(root.width() - 48, max(CONTRACT['window']['tabs_width'], footer_width)))
        for bar in (segments, footer_panel):
            shadow = QGraphicsDropShadowEffect(bar); shadow.setBlurRadius(12); shadow.setOffset(0, 2); shadow.setColor(QColor(31, 49, 75, 24)); bar.setGraphicsEffect(shadow)
        self.tools = ToolsPanel(self, self.content)
        self.settings = SettingsPanel(self)
        self.make_tts(); self.make_microphone(); self.make_stt(); self.settings.show_menu()
        if DEMO: self.footer.hide()
        self.shortcut_filter = ShortcutFilter(self); QApplication.instance().installEventFilter(self.shortcut_filter)
        self.caption_timer = QTimer(root); self.caption_timer.setSingleShot(True); self.caption_timer.timeout.connect(self.clear_caption)
        self.composer_timer = QTimer(root); self.composer_timer.timeout.connect(self.composer_tick)
        self.status.changed.connect(self.layout_overlays)
        self.navigation.raise_()
        self.update_busy()
        if not smoke:
            try: self.register_hotkeys()
            except RuntimeError as error: self.status.setText(localize_message(str(error)))
            self.make_tray()
            if self.config['microphone_enabled'] and self.config['tts_enabled']:
                QTimer.singleShot(0, lambda: self.microphone_toggle.setChecked(True))
            QTimer.singleShot(500, self.first_run)
            QTimer.singleShot(1500, self.warm_tts)
            QTimer.singleShot(5000, self.achievements.check)  # Report unlocks Steam missed while it was closed.

    @staticmethod
    def tint_on_check(control, name):
        paint = lambda: control.setIcon(icon_for(name, P['text'] if control.isChecked() else P['secondary']))
        control.toggled.connect(lambda _: paint()); theme.on_change(paint)

    def page(self):
        area = QScrollArea(); area.setWidgetResizable(True)
        content = QWidget(); layout = column(content, CONTRACT['window']['padding'], TOKENS['section_gap']); layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        padding = CONTRACT['window']['padding']; layout.setContentsMargins(padding, TOKENS['page_top'], padding, padding)
        area.setWidget(content); return area, layout

    def post(self, callback, *args):
        if not self.closing: self.bridge.dispatch.emit(callback, args)
    def report(self, message, active=None):
        def deliver():
            if active is not None and not active(): return
            if message.startswith(('TTS · ', 'STT · ')): self.backend_changed(message)
            else: self.status.setText(localize_message(message))
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
        line = row(); caption = label(tr(title)); caption.setWordWrap(False); caption.setMinimumWidth(64); line.addWidget(caption, 1)
        box = QComboBox()
        for value in values: box.addItem(tr(value), value)
        box.setCurrentIndex(box.findData(self.config[key])); box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents); line.addWidget(box)
        def update(index):
            value = box.itemData(index)
            if value is None: return
            self.config[key] = value; self.save()
            if changed: changed()
        box.currentIndexChanged.connect(update); layout.addLayout(line); self.boxes[key] = box
        return box, line

    def check(self, layout, title, key, changed=None, detail=''):
        control = CheckBox(tr(title), detail); control.setChecked(bool(self.config[key]))
        def update(enabled):
            try:
                if changed: changed(enabled)
                self.config[key] = enabled; self.save()
            except Exception as error:
                control.blockSignals(True); control.setChecked(self.config[key]); control.blockSignals(False); self.status.setText(localize_message(str(error)))
        control.toggled.connect(update); layout.addWidget(control); return control

    def scale(self, layout, title, key, changed=None, *, minimum=0, maximum=100, factor=100, suffix='%'):
        line = row(); line.setSpacing(12); caption = label(tr(title)); caption.setWordWrap(False); caption.setFixedWidth(84); line.addWidget(caption)
        slider = QSlider(Qt.Orientation.Horizontal); slider.setRange(minimum, maximum); slider.setValue(round(self.config[key] * factor))
        format_value = lambda value: f'{value / factor:.2f}×' if key == 'speed' else f'{value:+d}' if minimum < 0 else f'{value}{suffix}'
        number = label(format_value(slider.value()), muted=True); number.setFixedWidth(48); number.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        def update(value):
            self.config[key] = value / factor; number.setText(localize_message(format_value(value)))
            if changed: changed()
            if not slider.isSliderDown(): self.save()
        slider.valueChanged.connect(update); slider.sliderReleased.connect(self.save)
        line.addWidget(slider, 1); line.addWidget(number); layout.addLayout(line)
        if key in ('volume', 'pitch', 'speed'): self.voice_sliders[key] = slider
        return slider

    def reset_voice_controls(self):
        for key, value in [('volume', 100), ('pitch', 0), ('speed', 100)]: self.voice_sliders[key].setValue(value)

    def hotkey_slots(self):
        """Every assigned global shortcut as (slot, shortcut, action)."""
        slots = [('composer_key', self.config['composer_key'], self.show_composer)]
        if not DEMO: slots.append(('stt_key', self.config['stt_key'], self.toggle_stt))
        if self.config.get('skip_key'): slots.append(('skip_key', self.config['skip_key'], self.skip_tts))
        if DEMO: return slots
        for clip in self.soundboard.clips:
            if self.config.get('sound_keys', {}).get(clip['id']):
                slots.append(('sound:' + clip['id'], self.config['sound_keys'][clip['id']], lambda clip=clip: self.hotkey_sound(clip)))
        for preset in self.config.get('microphone_presets', []):
            if preset.get('hotkey'): slots.append(('preset:' + preset['id'], preset['hotkey'], lambda preset=preset: self.apply_microphone_preset(preset, toggle=True)))
        return slots
    def hotkey(self, slot):
        return next((value for name, value, _ in self.hotkey_slots() if name == slot), None)
    def set_hotkey(self, slot, value):
        kind, _, ident = slot.partition(':')
        if kind == 'sound':
            if value: self.config['sound_keys'][ident] = value
            else: self.config['sound_keys'].pop(ident, None)
        elif kind == 'preset':
            for preset in self.config['microphone_presets']:
                if preset['id'] == ident: preset['hotkey'] = value
        else: self.config[slot] = value

    def shortcut_button(self, slot, width=180, clearable=False):
        """A button that records a global shortcut for the slot; optional slots also get a clear button."""
        from winutil import shortcut_label
        holder = QWidget(); line = row(); line.setSpacing(4); holder.setLayout(line)
        control = button('', lambda: self.record_shortcut(slot)); control.setFixedSize(width, 26); line.addWidget(control)
        clear = None
        if clearable:
            clear = icon_button('xmark', tr('단축키 지우기'), lambda: self.clear_shortcut(slot)); line.addWidget(clear)
        def refresh():
            value = self.hotkey(slot)
            control.setText(localize_message(shortcut_label(value)) if value else tr('지정 안 함'))
            if clear: clear.setVisible(bool(value))
        control.refresh = refresh; refresh()
        self.shortcut_buttons[slot] = control
        return holder

    def shortcut_row(self, layout, title, key, clearable=False):
        line = row(); line.addWidget(label(tr(title))); line.addStretch()
        line.addWidget(self.shortcut_button(key, clearable=clearable)); layout.addLayout(line)

    def record_shortcut(self, key):
        if self.recording_key: self.finish_shortcut(); return
        if self.hotkeys: self.hotkeys.close(); self.hotkeys = None
        self.recording_key = key; self.shortcut_buttons[key].setText(tr('키를 누르세요 · Esc 취소'))
    def clear_shortcut(self, slot):
        if self.recording_key: self.finish_shortcut()
        self.set_hotkey(slot, None); self.save()
        try: self.register_hotkeys()
        except RuntimeError as error: self.status.setText(localize_message(str(error)))
        try: self.shortcut_buttons[slot].refresh()
        except (KeyError, RuntimeError): pass
    def finish_shortcut(self, candidate=None, error=None):
        from winutil import shortcut_data
        key = self.recording_key
        if not key: return
        self.recording_key = None; old = self.hotkey(key)
        try:
            if error: raise error
            if candidate is not None:
                if any(shortcut_data(value) == candidate for slot, value, _ in self.hotkey_slots() if slot != key):
                    raise ValueError('다른 기능과 겹치지 않는 단축키를 선택해 주세요.')
                self.set_hotkey(key, candidate)
            self.register_hotkeys()
            if candidate is not None: self.save(); self.count_hotkeys()
        except Exception as reason:
            self.set_hotkey(key, old)
            try: self.register_hotkeys()
            except RuntimeError: pass
            self.status.setText(localize_message(str(reason)))
        try: self.shortcut_buttons[key].refresh()
        except (KeyError, RuntimeError): pass  # The row was redrawn while recording.
    def register_hotkeys(self):
        if self.smoke: return
        from winutil import HotKeys
        if self.hotkeys: self.hotkeys.close(); self.hotkeys = None
        self.hotkeys = HotKeys({index: (value, lambda action=action: self.post(action))
                                for index, (_, value, action) in enumerate(self.hotkey_slots(), 1)})

    def feature_header(self, layout, name, control, detail, describe=None):
        """Leading page row: filled icon, bold switch title and a status line, as on macOS."""
        header = QWidget(); line = row(); line.setSpacing(12); header.setLayout(line)
        icon = QLabel(); icon.setFixedSize(32, 32); line.addWidget(icon)
        text = column(spacing=2); font = control.font(); font.setBold(True); font.setPixelSize(14); control.setFont(font); control.large = True
        control.setFixedHeight(24); text.addWidget(control); detail.setWordWrap(True); text.addWidget(detail); line.addLayout(text, 1)
        def refresh():
            if describe: message, active = describe(); detail.setText(message)
            else: active = control.isChecked()
            icon.setPixmap(badge(name, active)); restyle(detail, muted=not active, tone='accent' if active else '')
        control.toggled.connect(lambda _: refresh()); theme.on_change(refresh); self.header_refreshers.append(refresh)
        layout.addWidget(header).setMinimumHeight(56)
        return header

    def demo_notice(self, layout, text):
        """Explains a feature reserved for the full version, with a link to its store page."""
        line = row(); line.setSpacing(8); note = label(tr(text), tone='secondary'); line.addWidget(note, 1)
        line.addWidget(styled(button(tr('정식판 보기'), self.open_store), 'small')); layout.addLayout(line)
    @staticmethod
    def open_store():
        # The Steam client opens its own store page; a browser is the fallback.
        try: os.startfile('steam://store/' + STORE_URL.rstrip('/').split('/')[-1])
        except OSError:
            import webbrowser; webbrowser.open(STORE_URL)

    @staticmethod
    def accessory(text, symbol, callback):
        control = styled(button(text, callback), 'flat')
        theme.on_change(lambda: control.setIcon(icon_for(symbol, P['secondary'])))
        return control

    def make_tts(self):
        layout = section(self.tts_layout)
        self.tts_enabled = CheckBox(tr('TTS 사용')); self.tts_enabled.setChecked(self.config['tts_enabled'])
        self.tts_enabled.toggled.connect(self.toggle_tts_changed)
        self.feature_header(layout, 'TTS', self.tts_enabled, label(), lambda: (
            tr('STTS 연결됨') if self.tts_enabled.isChecked() else tr('TTS를 켜면 가상 마이크를 연결합니다.'), self.tts_enabled.isChecked()))
        self.shortcut_row(layout, tr('입력 단축키'), 'composer_key')
        self.shortcut_row(layout, tr('건너뛰기 단축키'), 'skip_key', clearable=True)
        self.option(layout, tr('사양'), 'tts', list(TTS_MODELS), self.refresh_voices)
        voice_layout = row(); caption = label(tr('목소리')); caption.setMinimumWidth(64); voice_layout.addWidget(caption, 1)
        self.voice_box = QComboBox(); self.voice_box.setMinimumWidth(180); self.voice_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents); voice_layout.addWidget(self.voice_box)
        self.voice_row = layout.addLayout(voice_layout)
        self.voice_box.currentIndexChanged.connect(self.voice_changed)
        language_row = row(); caption = label(tr('언어')); caption.setMinimumWidth(64); language_row.addWidget(caption, 1)
        self.language_box = QComboBox(); self.language_box.setMinimumWidth(205); self.language_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents); language_row.addWidget(self.language_box); layout.addLayout(language_row)
        self.language_box.currentIndexChanged.connect(self.language_changed)
        self.voice_monitoring = self.check(layout, tr('모니터링'), 'voice_monitoring', detail=tr('전송하는 TTS 목소리를 기본 스피커·헤드폰에서도 함께 듣습니다.'))
        adjust = section(self.tts_layout, tr('음성 조절'))
        adjust.accessory(self.accessory(tr('기본값 복원'), 'arrow.counterclockwise', self.reset_voice_controls))
        self.refresh_voices(); self.scale(adjust, tr('음량'), 'volume')
        self.scale(adjust, tr('피치'), 'pitch', minimum=-12, maximum=12, factor=1, suffix='')
        self.scale(adjust, tr('속도'), 'speed', minimum=50, maximum=200, factor=100, suffix='%')
        self.surface_controls(section(self.tts_layout, tr('입력창 모양')), 'window')

    def make_microphone(self):
        from microphone_effects import FILTERS
        mic_layout = section(self.microphone_layout)
        self.microphone_toggle = CheckBox(tr('마이크 함께 보내기'))
        self.microphone_toggle.toggled.connect(self.toggle_microphone)
        self.microphone_status = label(tr('마이크 전송 꺼짐'), muted=True)
        self.feature_header(mic_layout, '마이크', self.microphone_toggle, self.microphone_status,
            describe=lambda: (self.microphone_status.text(), self.microphone_active))
        mic_row = row(); mic_row.addWidget(label(tr('마이크')), 1)
        self.microphone_box = QComboBox(); self.microphone_box.setMinimumWidth(200); self.microphone_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents); mic_row.addWidget(self.microphone_box)
        self.microphone_refresh = icon_button('arrow.clockwise', tr('새로고침'), lambda: self.refresh_microphones(refresh=True), tint=theme.ACCENT)
        mic_row.addWidget(self.microphone_refresh); mic_layout.addLayout(mic_row)
        self.microphone_box.currentIndexChanged.connect(self.select_microphone)
        self.scale(mic_layout, tr('마이크 음량'), 'microphone_volume', self.microphone_volume_changed)
        effects_layout = section(self.microphone_layout, tr('마이크 효과'))
        if DEMO: self.demo_notice(effects_layout, '마이크 효과는 정식판에서 사용할 수 있습니다.')
        else: effects_layout.accessory(self.accessory(tr('기본값 복원'), 'arrow.counterclockwise', self.reset_microphone_effects))
        self.microphone_pitch_slider = self.scale(effects_layout, tr('피치'), 'microphone_pitch', self.microphone_effects_changed, minimum=-12, maximum=12, factor=1, suffix='')
        self.option(effects_layout, tr('필터'), 'microphone_filter', FILTERS, self.microphone_effects_changed)
        self.microphone_strength_slider = self.scale(effects_layout, tr('강도'), 'microphone_strength', self.microphone_effects_changed)
        if DEMO:
            for control in (self.microphone_pitch_slider, self.boxes['microphone_filter'], self.microphone_strength_slider): control.setEnabled(False)
        else: self.presets_layout = section(self.microphone_layout, tr('효과 프리셋')); self.show_microphone_presets()
        self.microphone_effects_changed()
        self.refresh_microphones()
        self.microphone_timer = QTimer(self.root); self.microphone_timer.setInterval(500)
        self.microphone_timer.timeout.connect(self.check_live_microphone)

    def refresh_microphones(self, *, refresh=False):
        from audio import physical_microphones
        try:
            if refresh:
                if self.tts_busy or self.voice_busy or self.capture or self.microphone_active:
                    raise RuntimeError('마이크 전송과 음성 작업을 멈춘 뒤 새로고침하세요.')
                import sounddevice as sd
                sd._terminate(); sd._initialize()
            devices = physical_microphones()
            self.microphone_box.blockSignals(True)
            self.microphone_box.clear(); self.microphone_box.addItem(tr('마이크 선택'), '')
            for device in devices: self.microphone_box.addItem(device['name'], device['id'])
            selected = self.microphone_box.findData(self.config['microphone_device'])
            self.microphone_box.setCurrentIndex(max(0, selected))
            self.microphone_box.blockSignals(False)
        except Exception as error: self.status.setText(localize_message(str(error)))

    def select_microphone(self):
        self.config['microphone_device'] = self.microphone_box.currentData() or ''; self.save()
        if self.config.get('microphone_enabled') and not self.microphone_active: self.microphone_retry_at = 0.0

    def microphone_volume_changed(self):
        self.live_microphone.volume = self.config['microphone_volume']

    def microphone_effects_changed(self):
        if DEMO: self.live_microphone.effect_settings = (0, '기본', 0); return
        self.live_microphone.effect_settings = (self.config['microphone_pitch'], self.config['microphone_filter'], self.config['microphone_strength'])
        self.count_filter()
        self.microphone_strength_slider.setEnabled(self.config['microphone_filter'] != '기본')

    def show_microphone_presets(self):
        """Saved pitch/filter/strength combinations, each with an optional global shortcut."""
        from PySide6.QtWidgets import QLineEdit
        layout = self.presets_layout
        while layout.rows.count():
            item = layout.rows.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        line = row(); name = QLineEdit(); name.setPlaceholderText(tr('프리셋 이름')); name.setAccessibleName(tr('프리셋 이름')); line.addWidget(name, 1)
        def save():
            title = name.text().strip()
            if not title: self.status.setText(tr('프리셋 이름을 입력해 주세요.')); return
            presets = self.config['microphone_presets']
            if any(preset['name'] == title for preset in presets): self.status.setText(tr('이미 있는 프리셋 이름입니다.')); return
            presets.append({'id': uuid.uuid4().hex, 'name': title, 'pitch': self.config['microphone_pitch'],
                            'filter': self.config['microphone_filter'], 'strength': self.config['microphone_strength'], 'hotkey': None})
            self.save(); self.show_microphone_presets()
        name.returnPressed.connect(save)
        line.addWidget(styled(button(tr('현재 효과 저장'), save), 'small')); layout.addLayout(line)
        for preset in self.config['microphone_presets']:
            line = row(); line.setSpacing(8)
            details = column(spacing=2); details.addWidget(label(preset['name']))
            details.addWidget(label(f"{tr(preset['filter'])} · {tr('피치')} {preset['pitch']:+.0f} · {tr('강도')} {round(preset['strength'] * 100)}%", muted=True)); line.addLayout(details, 1)
            line.addWidget(styled(button(tr('적용'), lambda p=preset: self.apply_microphone_preset(p)), 'small'))
            line.addWidget(self.shortcut_button('preset:' + preset['id'], width=120, clearable=True))
            line.addWidget(icon_button('trash', tr('삭제'), lambda p=preset: self.delete_microphone_preset(p), destructive=True))
            layout.addLayout(line)

    def apply_microphone_preset(self, preset, toggle=False):
        current = (self.config['microphone_pitch'], self.config['microphone_filter'], self.config['microphone_strength'])
        if toggle and current == (preset['pitch'], preset['filter'], preset['strength']):
            # Pressing an active preset's shortcut again returns to the plain microphone.
            self.reset_microphone_effects(); self.status.setText(tr('마이크 효과 끔')); return
        self.microphone_pitch_slider.setValue(round(preset['pitch']))
        self.boxes['microphone_filter'].setCurrentIndex(max(0, self.boxes['microphone_filter'].findData(preset['filter'])))
        self.microphone_strength_slider.setValue(round(preset['strength'] * 100))
        self.status.setText(localize_message('효과: ' + preset['name']))

    def delete_microphone_preset(self, preset):
        self.config['microphone_presets'] = [item for item in self.config['microphone_presets'] if item['id'] != preset['id']]
        self.save(); self.show_microphone_presets()
        if preset.get('hotkey'):
            try: self.register_hotkeys()
            except RuntimeError as error: self.status.setText(localize_message(str(error)))

    def count_filter(self):
        if self.microphone_active and self.config.get('microphone_filter', '기본') != '기본':
            self.achievements.include('filters', self.config['microphone_filter'])

    def reset_microphone_effects(self):
        self.microphone_pitch_slider.setValue(0)
        self.boxes['microphone_filter'].setCurrentIndex(self.boxes['microphone_filter'].findData('기본'))
        self.microphone_strength_slider.setValue(65)

    def toggle_microphone(self, enabled):
        if enabled and not self.config['tts_enabled']:
            self.microphone_toggle.blockSignals(True); self.microphone_toggle.setChecked(False); self.microphone_toggle.blockSignals(False)
            enabled = False
        self.config['microphone_enabled'] = enabled; self.save()
        if enabled:
            self.microphone_timer.start()
            self.start_live_microphone()
        else:
            self.microphone_timer.stop(); self.live_microphone.stop()
            self.microphone_active = False; self.microphone_retry_at = 0.0
            if self.status.text() == self.microphone_error: self.status.setText('')
            self.microphone_error = ''
            self.microphone_status.setText(tr('마이크 전송 꺼짐'))
            self.update_busy()

    def start_live_microphone(self):
        if self.closing or not self.config.get('microphone_enabled') or not self.config['tts_enabled']: return
        try:
            self.live_microphone.start(self.config.get('microphone_device', ''), self.config['microphone_volume'],
                refresh=not (self.tts_busy or self.voice_busy or self.capture))
            self.microphone_active = True; self.microphone_retry_at = 0.0
            if self.status.text() == self.microphone_error: self.status.setText('')
            self.microphone_error = ''
            self.microphone_status.setText(tr('● 내 말을 가상 마이크로 보내는 중')); self.count_filter()
        except Exception as error:
            self.live_microphone.stop()
            self.microphone_active = False; self.microphone_retry_at = time.monotonic() + 2.0
            self.microphone_error = localize_message(str(error))
            self.microphone_status.setText(tr('마이크 재연결 대기 중…')); self.status.setText(self.microphone_error)
        self.update_busy()

    def check_live_microphone(self):
        if self.closing or not self.config.get('microphone_enabled') or not self.config['tts_enabled']: return
        try:
            if self.live_microphone.active: return
        except Exception: pass
        if not self.microphone_retry_at:
            self.live_microphone.stop()
            self.microphone_active = False; self.microphone_retry_at = time.monotonic() + 2.0
            self.microphone_error = tr('마이크 연결이 끊어졌습니다. 같은 마이크에 다시 연결하는 중입니다.')
            self.microphone_status.setText(tr('마이크 재연결 대기 중…')); self.status.setText(self.microphone_error)
            self.update_busy()
        elif time.monotonic() >= self.microphone_retry_at:
            self.start_live_microphone()

    def show_setup(self):
        dialog = QDialog(self.root); dialog.setObjectName('main'); dialog.setWindowTitle(localize_message(CONTRACT['onboarding']['title'])); dialog.setFixedWidth(480)
        layout = column(dialog, 28, 12)
        heading = row(); heading.setSpacing(12); icon = QLabel(); icon.setPixmap(badge('TTS', True, 40)); heading.addWidget(icon)
        title = label(tr(CONTRACT['onboarding']['title']), title=True); heading.addWidget(title, 1); layout.addLayout(heading); layout.addSpacing(8)
        steps = []
        for item in CONTRACT['onboarding']['sections']:
            step = QFrame(); step.setObjectName('step'); body = column(step, 16, 6)
            text = label(tr(item['text']), muted=True); steps.append(text)
            body.addWidget(label(tr(item['title']), heading=True)); body.addWidget(text); layout.addWidget(step)
        def done():
            if not self.config.get('setup_completed'):
                from winutil import set_login
                try: set_login(self.config['login'])
                except OSError as error:
                    QMessageBox.warning(dialog, tr('로그인 시 자동 실행'), str(error)); return
            self.config['setup_completed'] = True; self.save(); dialog.accept()
        line = row(); line.addStretch(); start = styled(button(tr(CONTRACT['onboarding']['button']), done), 'primary'); start.setMinimumHeight(30)
        start.setDefault(True); line.addWidget(start); layout.addLayout(line)
        # Wrapped text inside the step cards is measured at its real width (dialog minus page and card margins).
        for text in steps: text.setFixedHeight(text.heightForWidth(dialog.width() - 2 * 28 - 2 * 16))
        dialog.adjustSize(); dialog.setFixedHeight(dialog.sizeHint().height())
        if self.smoke:
            def snapshot():
                dialog.grab().save(str(DATA / 'ui/setup.png')); dialog.reject()
            QTimer.singleShot(300, snapshot)
        dialog.exec()

    def first_run(self):
        if not self.config.get('setup_completed'): self.show_setup()
        from driver_setup import driver_exists, installer
        # Only copies that carry the VB-CABLE package (Steam) offer setup; STTS Setup installs it already.
        if getattr(sys, 'frozen', False) and installer().is_file() and not driver_exists(): self.check_microphone()

    def check_microphone(self):
        if self.tts_busy or self.voice_busy or self.capture or self.microphone_toggle.isChecked():
            self.status.setText(tr('음성 작업이 끝난 뒤 연결을 확인하세요.')); return
        dialog = QDialog(self.root); dialog.setObjectName('main'); dialog.setWindowTitle(tr('가상 마이크 연결 점검')); dialog.setMinimumWidth(520)
        layout = column(dialog, 20)
        title = label(tr('가상 마이크 연결 점검'), title=True); layout.addWidget(title)
        message = label(tr('장치 확인 중…')); layout.addWidget(message)
        controls = []
        def finished(result):
            message.setText(localize_message(result['message']))
            for control in controls: control.setEnabled(True)
        def run_check(signal=False, repair=False):
            for control in controls: control.setEnabled(False)
            message.setText(localize_message('케이블 테스트 중…' if signal else '케이블 확인 중…'))
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
            control = button(tr(title), action); controls.append(control); line.addWidget(control)
        layout.addLayout(line)
        layout.addWidget(label(tr('신호 테스트를 누르면 가상 마이크로 1초 테스트음이 전송됩니다. 통화 밖에서 실행하세요.'), muted=True))
        line = row()
        def install_driver():
            # Steam copies have no installer step, so STTS installs VB-CABLE itself behind one UAC prompt.
            for control in controls: control.setEnabled(False)
            message.setText(tr('가상 마이크를 설치하는 중…'))
            def work():
                from driver_setup import setup
                try: result = setup()
                except Exception as error: result = str(error)
                self.post(lambda: run_check() if result is None else finished({'message': result}))
            threading.Thread(target=work, daemon=True).start()
        driver = button(tr('가상 마이크 설치'), install_driver); controls.append(driver); line.addWidget(driver)
        line.addWidget(button(tr('Windows 소리 설정'), lambda: os.startfile('ms-settings:sound')))
        line.addWidget(button(tr('마이크 권한'), lambda: os.startfile('ms-settings:privacy-microphone'))); layout.addLayout(line)
        line = row(); line.addStretch(); line.addWidget(styled(button(tr('닫기'), dialog.accept), 'primary')); layout.addLayout(line)
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
                self.voice_box.addItem(profile['name'] or tr('이름·대본 필요'), 'clone:' + profile['id'])
                self.voice_box.model().item(self.voice_box.count() - 1).setEnabled(voice_ready(profile, self.voice_root))
        selected = 'clone:' + self.config['selected_clone_id'] if tier in ('중간', '높음') and self.config.get('selected_clone_id') else 'preset:' + self.config['voice']
        index = self.voice_box.findData(selected)
        if index < 0 and presets: index = 0; self.config['voice'] = presets[0]
        self.voice_box.setCurrentIndex(index); self.voice_box.blockSignals(False); self.voice_row.setVisible(tier != '기본')
        self.refresh_languages(); self.save(); self.warm_tts()
    def voice_changed(self, index):
        value = self.voice_box.itemData(index)
        if not value: return
        if value.startswith('clone:'): self.config['selected_clone_id'] = value.removeprefix('clone:')
        else: self.config['selected_clone_id'] = None; self.config['voice'] = value.removeprefix('preset:')
        self.save(); self.warm_tts()
    def refresh_languages(self):
        key = {'기본': 'gtts', '낮음': 'supertonic3'}.get(self.config['tts'], 'qwenTTS')
        codes = SPEECH_LANGUAGES[key]; self.language_box.blockSignals(True); self.language_box.clear()
        ordered = [code for code in CONTRACT['language_order'] if code in codes]
        ordered += sorted(code for code in codes if code not in ordered)
        preferred = system_languages() if self.config['language_follows_system'] else [self.config['language']]
        self.config['language'] = speech_language(preferred, ordered)
        self.language_box.addItem(tr('시스템 언어 · {0}', language_name(self.config['language'])), 'system')
        for code in ordered:
            self.language_box.addItem(f"{language_name(code)} · {code}", code)
        selected = 'system' if self.config['language_follows_system'] else self.config['language']
        self.language_box.setCurrentIndex(self.language_box.findData(selected)); self.language_box.blockSignals(False)
    def language_changed(self, index):
        code = self.language_box.itemData(index)
        if code is None: return
        self.config['language_follows_system'] = code == 'system'
        if code != 'system': self.config['language'] = code
        self.refresh_languages(); self.save()

    def surface_controls(self, layout, prefix):
        backdrop = QFrame(); backdrop.setObjectName('preview'); inner = column(backdrop, 18, 0)
        preview = QLabel(localize_message('음성 입력창 미리보기' if prefix == 'window' else '자막 미리보기'))
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter); preview.setWordWrap(True); preview.setMinimumHeight(44 if prefix == 'window' else 56)
        inner.addWidget(preview); layout.addWidget(backdrop)
        setattr(self, prefix + '_preview', preview)
        for text, suffix in [('배경', 'bg'), ('글자', 'color')]:
            key = prefix + '_' + suffix
            line = row(); line.addWidget(label(tr(text)), 1)
            control = ColorWell(lambda key=key: self.pick_color(key)); control.setAccessibleName(localize_message(text + ' 색상'))
            self.color_buttons[key] = control; line.addWidget(control); layout.addLayout(line)
        opacity = self.scale(layout, tr('불투명도'), prefix + '_alpha', self.refresh_surfaces)
        size = self.scale(layout, tr('글자 크기'), 'caption_font', self.refresh_surfaces, minimum=14, maximum=40, factor=1, suffix='') if prefix == 'caption' else None
        if DEMO:
            for control in [opacity, size, *(self.color_buttons[prefix + '_' + suffix] for suffix in ('bg', 'color'))]:
                if control: control.setEnabled(False)
            self.demo_notice(layout, '모양 꾸미기는 정식판에서 사용할 수 있습니다.')
        self.refresh_surfaces()
    def rgba(self, prefix):
        color = QColor(self.config[prefix + '_bg'])
        return f'rgba({color.red()}, {color.green()}, {color.blue()}, {round(self.config[prefix + "_alpha"] * 255)})'
    def refresh_surfaces(self):
        for key, control in getattr(self, 'color_buttons', {}).items():
            control.set_color(self.config[key])
        for prefix in ('window', 'caption'):
            preview = getattr(self, prefix + '_preview', None)
            if preview:
                preview.setStyleSheet(f'background: {self.rgba(prefix)}; color: {self.config[prefix + "_color"]}; border-radius: 10px; padding: 8px 16px; font-weight: 500; font-size: {13 if prefix == "window" else int(self.config["caption_font"])}px;')
        if self.composer:
            choices = self.composer.findChild(QListWidget)
            if choices: choices.setStyleSheet(f"QListWidget {{ background: transparent; color: {self.config['window_color']}; border: none; padding: 0; font-size: 13px; outline: none; }} QListWidget::item:selected {{ background: rgba(49,130,246,45); color: {self.config['window_color']}; border-radius: 8px; }}")
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
        if not enabled:
            self.microphone_toggle.setChecked(False)
            self.cancel_tts(); self.hide_composer()
        else: self.warm_tts()
        self.update_busy()
    def submit(self, widget):
        if getattr(widget, 'preedit', False): return
        input_text = unicodedata.normalize('NFC', widget.text().strip())
        phrases = {} if DEMO else self.config.get('tts_phrases', {})
        text = phrases.get(input_text, input_text)
        if not self.tts_enabled.isChecked(): self.status.setText(tr('TTS를 켜세요.')); return
        if self.voice_busy: self.status.setText(tr('현재 음성 작업이 끝난 후 다시 전송하세요.')); return
        if not 1 <= len(text) <= CONTRACT['limits']['text']: self.status.setText(tr('1~500자를 입력하세요.')); return
        if input_text not in phrases and not DEMO:
            try: clip = self.soundboard.clip_for_input(input_text)
            except ValueError as error:
                self.status.setText(localize_message(str(error)))
                QToolTip.showText(widget.mapToGlobal(QPoint(0, widget.height() + 10)), localize_message(str(error)), widget, msecShowTime=10000)
                return
            else:
                if clip is not None:
                    if self.tts_busy:
                        self.tts_queue.append(('sound', dict(clip))); self.remember_sent(input_text); widget.clear(); self.hide_composer(); self.update_busy()
                    elif self.play_sound(clip): self.remember_sent(input_text); widget.clear(); self.hide_composer()
                    else: QToolTip.showText(widget.mapToGlobal(QPoint(0, widget.height() + 10)), self.status.text(), widget, msecShowTime=10000)
                    return
        from audio import cable_output
        try:
            if not self.tts_busy: cable_output(refresh=self.live_microphone.stream is None)
        except Exception as error:
            self.status.setText(localize_message(str(error)))
            QToolTip.showText(widget.mapToGlobal(QPoint(0, widget.height() + 10)), localize_message(str(error)), widget, msecShowTime=10000)
            return
        request = {'action': 'tts', 'text': text, 'root': str(self.model_root), 'language': self.config['language'], 'voice': self.config['voice'], 'pitch': self.config.get('pitch', 0), 'speed': self.config.get('speed', 1)}
        model, profile = self.tts_model()
        if profile and not voice_ready(profile, self.voice_root):
            self.status.setText(tr('하단 보이스 클론에서 선택한 목소리의 이름과 대본을 확인해 주세요.')); return
        if profile: request.update(reference=str(self.voice_root / (profile['id'] + '.wav')), transcript=profile['transcript'], voice_root=str(self.voice_root))
        request['model'] = model; self.remember_sent(input_text); widget.clear(); self.hide_composer()
        if self.tts_busy:
            self.tts_queue.append(('tts', request)); self.update_busy(); return
        self.start_tts(request)

    def spoke(self, language):
        self.achievements.count('tts'); self.achievements.include('languages', language)
        if 2 <= time.localtime().tm_hour < 5: self.achievements.level('night', 1)
    def count_hotkeys(self):
        self.achievements.level('hotkeys', len(self.config.get('sound_keys', {})) + sum(1 for preset in self.config.get('microphone_presets', []) if preset.get('hotkey')))

    def remember_sent(self, text):
        # Recent inputs for ↑/↓ in the input box; kept in memory only.
        self.sent_history = [item for item in self.sent_history if item != text][-49:] + [text]

    def hotkey_sound(self, clip):
        if not self.tts_enabled.isChecked() or clip not in self.soundboard.clips: return
        if self.playing_sound == clip['id']: self.cancel_tts()
        elif self.tts_busy: self.tts_queue.append(('sound', dict(clip))); self.update_busy()
        else: self.play_sound(clip)

    def tts_model(self):
        """The worker model for the current tier and voice, and the clone profile it needs, if any."""
        model = TTS_MODELS[self.config['tts']]
        if not model.startswith('qwen'): return model, None
        profile = next((p for p in self.profiles if p['id'] == self.config.get('selected_clone_id')), None)
        return (model, profile) if profile else (model + 'Custom', None)
    def warm_tts(self):
        """Loads the selected voice model before the first sentence so speaking does not wait for it."""
        model, _ = self.tts_model()
        if self.closing or self.smoke or self.tts_busy or not self.config['tts_enabled'] or model == 'gtts': return
        worker, token = self.tts_worker, self.audio_stop
        request = {'action': 'preload', 'model': model, 'root': str(self.model_root)}
        def run():
            try: worker.request(request)
            except Exception: return  # The next sentence loads the model and reports any error.
            self.post(self.release_idle_tts, token)
        threading.Thread(target=run, daemon=True).start()
    def release_idle_tts(self, token):
        # Keep the voice model in VRAM between sentences; free it only after a long idle period.
        worker = self.tts_worker
        def release():
            if self.closing or self.tts_busy or self.audio_stop is not token or self.tts_worker is not worker: return
            worker.stop(); self.tts_worker = self.make_tts_worker()
        QTimer.singleShot(int(CONTRACT['limits']['model_idle_seconds'] * 1000), release)
    def start_tts(self, request):
        self.tts_busy = True
        self.audio_stop = threading.Event(); token = self.audio_stop; worker = self.tts_worker
        monitoring = self.config['voice_monitoring']
        self.status.setText(tr('음성 생성 중…')); self.update_busy()
        def run():
            try:
                import numpy as np
                from audio import play_cable
                result = worker.request(request)
                warning = ''
                if not token.is_set():
                    self.report('가상 마이크로 보내는 중…', active=lambda: self.audio_stop is token and not token.is_set())
                    warning = play_cable(np.frombuffer(base64.b64decode(result['audio']), dtype='<f4'), result['rate'], lambda: self.config['volume'], token, monitor=monitoring)
                if not token.is_set(): self.spoke(request['language'])
                self.post(self.finish_tts, token, warning or '')
            except Exception as error:
                if not token.is_set() or token is self.skipping: self.post(self.finish_tts, token, str(error), True)
        threading.Thread(target=run, daemon=True).start()
    def finish_tts(self, token, message, failed=False):
        if token is not self.audio_stop: return
        if token.is_set():
            # A skipped sentence ends quietly and the queue moves on.
            if token is not self.skipping: return
            message, failed = '', False
        self.skipping = None
        self.playing_sound = None
        self.tts_busy = False
        if failed: self.tts_queue.clear()
        self.status.setText(localize_message(message)); self.update_busy()
        if self.tts_queue:
            kind, value = self.tts_queue.pop(0)
            if kind == 'tts': self.start_tts(value)
            elif not self.play_sound(value): self.tts_queue.clear(); self.update_busy()
            return
        self.release_idle_tts(token)
    def skip_tts(self):
        """Stops the sentence or sound being sent and moves on to the next queued one."""
        if not self.tts_busy: return
        if not self.tts_queue: self.cancel_tts(); return
        # Playback stops at once; a sentence still being generated is dropped when the worker returns it.
        self.skipping = self.audio_stop; self.audio_stop.set(); self.status.setText(tr('건너뛰는 중…'))
    def cancel_tts(self):
        self.skipping = None; self.tts_queue.clear()
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
        field = ComposerEdit(); field.setFixedHeight(24); field.setPlaceholderText(tr('입력 후 Enter')); layout.addWidget(field)
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
        recall = {'index': len(self.sent_history), 'draft': '', 'active': False}
        def recall_sent(step):
            # ↑/↓ walk through recently sent inputs, then back to the unsent draft.
            history = self.sent_history
            if not history: return
            if recall['index'] == len(history): recall['draft'] = field.text()
            recall['index'] = max(0, min(len(history), recall['index'] + step)); recall['active'] = True
            field.setText(history[recall['index']] if recall['index'] < len(history) else recall['draft']); field.end(False)
        def typed(_):
            recall['active'] = False; recall['index'] = len(self.sent_history)
        field.recalled.connect(recall_sent); field.textEdited.connect(typed)
        def update_completions():
            from interaction import completion_candidates
            items = [] if field.preedit or recall['active'] or DEMO else completion_candidates(field.text(), self.config.get('tts_phrases', {}), [clip['name'] for clip in self.soundboard.clips])
            choices.clear()
            for name, kind in items:
                item = QListWidgetItem(name + '  ·  ' + tr(kind)); item.setData(Qt.ItemDataRole.UserRole, name); item.setSizeHint(QSize(0, 32)); choices.addItem(item)
            choices.setVisible(bool(items)); field.has_completions = bool(items)
            extra = len(items) * 32 + 8 if items else 0
            choices.setFixedHeight(extra); choices.setCurrentRow(0 if items else -1)
            window.setGeometry(x, max(area.top() + 8, min(y, area.bottom() - height - extra - 7)), width, height + extra)
        field.textChanged.connect(update_completions); field.compositionChanged.connect(update_completions)
        field.navigated.connect(lambda step: choices.setCurrentRow((choices.currentRow() + step) % choices.count()) if choices.count() else None)
        field.completed.connect(fill_completion); choices.itemClicked.connect(lambda _: fill_completion())
        field.setText(self.composer_draft); field.end(False)
        def focus_input():
            if self.composer is window and window.isVisible():
                from winutil import root_handle
                user32.SetForegroundWindow(root_handle(window))
                window.activateWindow(); field.setFocus(); field.end(False)
        QTimer.singleShot(0, focus_input)
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
        if self.composer:
            self.composer_draft = self.composer.findChild(ComposerEdit).text() if self.config['keep_draft'] else ''
            self.composer.close(); self.composer.deleteLater(); self.composer = None
        if restore_focus and getattr(self, 'previous_window', None):
            from winutil import user32
            user32.SetForegroundWindow(self.previous_window)
        self.previous_window = None

    def make_stt(self):
        layout = section(self.stt_layout)
        self.stt_enabled = CheckBox(tr('STT 사용')); self.stt_enabled.clicked.connect(self.toggle_stt)
        self.feature_header(layout, 'STT', self.stt_enabled, label(), lambda: (
            tr('Discord 수신 중') if self.capture else tr('자막 꺼짐'), bool(self.capture)))
        if DEMO:
            self.stt_enabled.setEnabled(False); self.demo_notice(layout, '실시간 자막은 정식판에서 사용할 수 있습니다.')
        else:
            self.shortcut_row(layout, tr('자막 단축키'), 'stt_key')
        self.option(layout, tr('사양'), 'stt', list(STT_MODELS), self.stt_model_changed)
        if DEMO: self.boxes['stt'].setEnabled(False)
        self.history = QLabel(); self.history.setWordWrap(True); self.history.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.history.hide(); self.stt_layout.addWidget(self.history)
        self.surface_controls(section(self.stt_layout, tr('자막 모양')), 'caption')
    def stt_model_changed(self):
        if self.capture: self.stop_stt(); self.toggle_stt()
    def toggle_stt(self):
        if self.capture: self.stop_stt(); return
        if DEMO: self.stt_enabled.setChecked(False); return
        if self.voice_busy: self.stt_enabled.setChecked(False); self.status.setText(tr('목소리 저장이 끝난 뒤 STT를 켜세요.')); return
        from audio import Capture, Worker
        def progress(message): self.report(message, active=lambda: self.capture is capture)
        def caption(text): self.post(lambda: self.show_caption(text) if self.capture is capture else None)
        capture = Capture(self.job, Worker(self.job, progress), STT_MODELS[self.config['stt']], self.model_root,
                          caption, progress, lambda: self.post(self.capture_ended, capture))
        try: capture.start()
        except Exception as error: capture.stop(); self.stt_enabled.setChecked(False); self.status.setText(localize_message(str(error))); return
        self.capture = capture; self.stt_enabled.setChecked(True); self.show_caption(''); self.status.setText(tr('STT 준비 중…')); self.update_busy()
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
            self.history.setStyleSheet(f'background: {self.rgba("caption")}; color: {self.config["caption_color"]}; border-radius: {TOKENS["card_radius"]}px; padding: 16px;')
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
        self.caption_label.setStyleSheet(f'background: {self.rgba("caption")}; color: {self.config["caption_color"]}; font-size: {int(self.config["caption_font"])}px; font-weight: 500; border-radius: {int(CONTRACT["caption"]["radius"])}px; padding: {int(CONTRACT["caption"]["padding"])}px;')
        self.caption.setFixedWidth(width); self.caption_label.setFixedWidth(width)
        height = max(56, self.caption_label.heightForWidth(width), self.caption_label.sizeHint().height())
        height = min(height, area.height() - 40)
        self.caption.setFixedHeight(height)
        self.caption.move(area.left() + (area.width() - width) // 2, max(area.top() + 20, area.bottom() - int(self.config['caption_y']) - height))

    def select_tab(self, index):
        if self.recording_key: self.finish_shortcut()
        if self.voice_cancel: self.voice_cancel()
        self.tools.dismiss()
        self.tabs.setCurrentIndex(index); self.tab_buttons.button(index).setChecked(True); self.footer.setVisible(index == 0 and not DEMO); self.layout_overlays()
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
        self.config['tts_phrases'] = phrases; self.achievements.level('phrases', len(phrases))
    def delete_tts_phrase(self, shortcut):
        phrases = dict(self.config.get('tts_phrases', {})); phrases.pop(shortcut, None)
        write_json(DATA / 'settings.json', dict(self.config, tts_phrases=phrases))
        self.config['tts_phrases'] = phrases

    def add_sound_files(self, paths=None, name=None):
        if self.tts_busy or self.voice_busy: self.status.setText(tr('현재 음성 작업이 끝난 뒤 파일을 추가하세요.')); return
        if paths is None: paths, _ = QFileDialog.getOpenFileNames(self.root, tr('사운드 추가'), '', tr('음성 파일 (*.wav *.mp3 *.m4a *.aiff *.aif *.flac)'))
        if not paths: return
        self.voice_busy = True; self.update_busy(); self.status.setText(tr('사운드 가져오는 중…'))
        def run():
            from audio import Worker
            import numpy as np
            worker = Worker(self.job, self.report); errors = []
            try:
                for path in paths:
                    try:
                        result = worker.request({'action': 'decode_sound', 'path': path})
                        samples = np.frombuffer(base64.b64decode(result['audio']), dtype='<f4')
                        self.soundboard.import_samples(name if name and len(paths) == 1 else Path(path).stem, samples, 24000, self.config.get('tts_phrases', {}))
                    except Exception as error: errors.append(Path(path).name + ': ' + str(error))
            finally: worker.stop()
            self.post(self.finish_sound_import, errors)
        threading.Thread(target=run, daemon=True).start()

    def finish_sound_import(self, errors):
        self.voice_busy = False; self.update_busy(); self.status.setText(localize_message('\n'.join(errors)))
        if self.tools.active == 'soundboard': self.tools.show_sounds()

    def delete_sound(self, clip):
        if self.tts_busy or self.voice_busy: return
        if QMessageBox.question(self.root, tr('사운드를 삭제할까요?'), localize_message(clip['name'] + ' 등록을 삭제합니다. 가져온 원본 파일은 유지됩니다.')) != QMessageBox.StandardButton.Yes: return
        try: self.soundboard.remove(clip)
        except (OSError, ValueError) as error: self.status.setText(localize_message(str(error))); return
        if self.config['sound_keys'].pop(clip['id'], None):
            self.save()
            try: self.register_hotkeys()
            except RuntimeError as error: self.status.setText(localize_message(str(error)))
        self.tools.show_sounds()

    def play_sound(self, clip):
        if not self.tts_enabled.isChecked(): self.status.setText(tr('TTS 사용을 켜 주세요.')); return False
        if self.tts_busy or self.voice_busy: self.status.setText(tr('현재 음성 작업이 끝난 뒤 재생해 주세요.')); return False
        from audio import cable_output, play_cable
        try: cable_output(refresh=self.live_microphone.stream is None)
        except Exception as error: self.status.setText(localize_message(str(error))); return False
        self.audio_stop = threading.Event(); token = self.audio_stop
        self.tts_busy = True; self.playing_sound = clip['id']; self.update_busy(); self.status.setText(localize_message(clip['name'] + ' 재생 중…'))
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
                if not token.is_set(): self.achievements.count('sounds')
                self.post(self.finish_tts, token, warning or '')
            except Exception as error:
                if not token.is_set() or token is self.skipping: self.post(self.finish_tts, token, str(error), True)
        threading.Thread(target=run, daemon=True).start()
        return True

    def save_profiles(self):
        write_json(self.voice_root / 'profiles.json', self.profiles); self.refresh_voices()
        self.achievements.level('clones', sum(1 for item in self.profiles if voice_ready(item, self.voice_root)))
    def delete_voice(self, profile):
        if self.tts_busy or self.voice_busy: self.status.setText(tr('음성 작업이 끝난 뒤 삭제하세요.')); return
        if QMessageBox.question(self.root, tr('목소리 삭제'), localize_message(f"{profile['name']} 목소리를 삭제할까요?")) != QMessageBox.StandardButton.Yes: return
        from send2trash import send2trash
        path = self.voice_root / (profile['id'] + '.wav')
        if path.exists(): send2trash(str(path))
        self.profiles.remove(profile); self.save_profiles(); self.tools.show_voices()
    def add_voice_files(self, paths=None, name=None):
        if self.tts_busy or self.voice_busy or self.capture: self.status.setText(tr('TTS와 STT를 멈춘 뒤 목소리를 추가하세요.')); return
        if paths is None: paths, _ = QFileDialog.getOpenFileNames(self.root, tr('목소리 추가'), '', tr('음성 파일 (*.mp3 *.wav *.m4a *.aiff *.aif)'))
        if not paths: return
        self.voice_busy = True; self.update_busy()
        def run():
            for index, path in enumerate(paths):
                self.store_voice((name if name and len(paths) == 1 else Path(path).stem, ''), None, path, more=index < len(paths) - 1)
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
            profile = {'id': ident, 'name': name, 'transcript': transcript, 'source_name': Path(path).name if path else tr('마이크 녹음') + '.wav'}
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
            self.status.setText(tr('음성·자막 작업이 끝난 뒤 대본을 입력하세요.')); return
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
                self.tools.set_voice_transcribing(False); self.status.setText(localize_message(error)); return
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
            self.status.setText(localize_message(error))
            if not more and self.tools.active == "voice": self.tools.show_voices()
            return
        self.save_profiles(); self.status.setText(localize_message(error or ''))
        if not more and self.tools.active == "voice": self.tools.edit_voice(profile)

    def delete_model(self, path):
        if self.tts_busy or self.capture or self.voice_busy: self.status.setText(tr('음성 작업을 모두 멈춘 뒤 삭제하세요.')); return
        if path.parent != self.model_root or path.is_symlink(): return
        if QMessageBox.question(self.root, tr('모델을 삭제할까요?'), localize_message(f'{path.name}\n다음 사용 시 다시 다운로드합니다.')) != QMessageBox.StandardButton.Yes: return
        self.cancel_tts(); shutil.rmtree(path); self.settings.show_models()
    def update_busy(self):
        self.queue_label.setText(tr('대기 {0}개').format(len(self.tts_queue)))
        self.queue_label.setVisible(bool(self.tts_queue))
        enabled = self.tts_enabled.isChecked() and not (self.tts_busy or self.voice_busy)
        self.boxes['tts'].setEnabled(enabled); self.voice_box.setEnabled(enabled); self.language_box.setEnabled(enabled)
        self.voice_monitoring.setEnabled(enabled)
        mic_on = self.microphone_toggle.isChecked()
        self.microphone_toggle.setEnabled(mic_on or self.tts_enabled.isChecked())
        self.microphone_box.setEnabled(not self.microphone_active)
        self.microphone_refresh.setEnabled(not (self.microphone_active or self.tts_busy or self.voice_busy or self.capture))
        for key in ('pitch', 'speed'): self.voice_sliders[key].setEnabled(not self.tts_busy)
        self.boxes['stt'].setEnabled(not (self.capture or self.voice_busy or DEMO)); self.tts_cancel.setVisible(self.tts_busy); self.status.dismiss.setVisible(not self.tts_busy); self.status.fit_content(); self.layout_overlays()
        self.tools.update_sound_controls()
        for refresh in self.header_refreshers: refresh()
    @property
    def overlay_bottom(self):
        return (60 if self.tabs.currentIndex() == 0 and not DEMO else 0) + (44 if self.status.text() else 0)

    def layout_overlays(self):
        self.footer.move((self.root.width() - self.footer.width()) // 2, self.root.height() - 50)
        self.status_slot.setFixedSize(self.status.width() + 48, 44)
        self.status_slot.move((self.root.width() - self.status_slot.width()) // 2, self.root.height() - self.overlay_bottom)
        padding = CONTRACT['window']['padding']
        for index, layout in enumerate((self.tts_layout, self.microphone_layout, self.stt_layout, self.settings_layout)):
            layout.setContentsMargins(padding, TOKENS['page_top'], padding, padding + (60 if index == 0 and not DEMO else 0) + (44 if self.status.text() else 0))
        if hasattr(self, 'tools'): self.tools.panel.resize(self.content.width() - 24, self.content.height() - 80 - self.overlay_bottom)
        self.navigation.raise_(); self.footer.raise_(); self.status_slot.raise_()

    def make_tray(self):
        self.tray = QSystemTrayIcon(icon_for('TTS 단축어'), self.root); self.tray.setToolTip(tr('STTS')); menu = QMenu()
        for title, callback in [('STTS 열기', self.show), ('입력창 열기', self.show_composer), ('자막 중지', self.stop_stt), ('완전 종료', self.quit)]: menu.addAction(tr(title)).triggered.connect(callback)
        self.tray.setContextMenu(menu); self.tray.activated.connect(lambda reason: self.show() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show(); self.tray_menu = menu
    def show(self): self.root.showNormal(); self.root.raise_(); self.root.activateWindow()
    def close_window(self):
        self.tools.dismiss(animated=False)
        if self.recording_key: self.finish_shortcut()
        if self.voice_cancel: self.voice_cancel()
        if self.config['close'] == '최소화': self.root.showMinimized()
        else: self.root.hide()
    def quit(self):
        if self.closing: return
        if self.recording_key: self.finish_shortcut()
        if self.voice_cancel: self.voice_cancel()
        self.closing = True; self.save(); self.audio_stop.set()
        if hasattr(self, 'runtime_control'): self.runtime_control.stop()
        self.microphone_timer.stop(); self.live_microphone.stop()
        if self.capture: self.capture.stop()
        self.tts_worker.stop()
        if self.hotkeys: self.hotkeys.close()
        if self.tray: self.tray.hide()
        self.job.close(); self.root.close(); QApplication.instance().quit()
    def restart(self):
        import subprocess
        # The launcher waits for this runtime to exit, then starts it again with the saved settings.
        if getattr(sys, 'frozen', False): command = [str(Path(sys.executable).with_name('STTS.exe'))]
        else: command = [sys.executable, str(Path(__file__).with_name('launcher.py'))]
        subprocess.Popen(command + ['--restart', str(os.getpid())], creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)
        self.quit()


class ControlServer:
    def __init__(self, root):
        from PySide6.QtNetwork import QLocalServer
        from runtime import control_name, RuntimeInstance
        self.app = None
        self.instance = RuntimeInstance(control_name()) if sys.platform == 'win32' else None
        if self.instance and self.instance.duplicate:
            self.instance.close(); raise RuntimeError('STTS runtime is already running')
        self.server = QLocalServer(root)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self.server.listen(control_name()):
            if self.instance: self.instance.close()
            raise RuntimeError(self.server.errorString())
        self.server.newConnection.connect(self.accept)

    def accept(self):
        while self.server.hasPendingConnections():
            connection = self.server.nextPendingConnection()
            connection.readyRead.connect(lambda connection=connection: self.receive(connection))
            connection.disconnected.connect(connection.deleteLater)
            self.receive(connection)

    def receive(self, connection):
        if self.app is None: connection.abort(); return
        if connection.bytesAvailable() > 4096: connection.abort(); return
        if not connection.canReadLine(): return
        try: command = json.loads(bytes(connection.readLine()))['command']
        except (ValueError, KeyError, TypeError): connection.abort(); return
        if command not in ('status', 'show', 'hide', 'quit'): connection.abort(); return
        if command == 'show': self.app.show()
        elif command == 'hide': self.app.close_window()
        response = {'pid': os.getpid(), 'version': VERSION, 'build': CONTRACT['build'], 'visible': self.app.root.isVisible()}
        connection.write(json.dumps(response).encode() + b'\n'); connection.flush()
        connection.waitForBytesWritten(1000)
        connection.disconnectFromServer()
        if command == 'quit':
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self.app.quit)

    def stop(self): self.server.close()


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
    if '--install-driver' in sys.argv:
        from driver_setup import install_elevated
        raise SystemExit(install_elevated())
    if '--diagnose-audio' in sys.argv:
        from setup_check import inspect, signal_test
        DATA.mkdir(parents=True, exist_ok=True)
        result = {'version': VERSION, 'ok': False}
        try:
            result.update(signal_test() if '--signal-test' in sys.argv else inspect())
        except Exception as error: result['error'] = str(error)
        write_json(DATA / 'audio-diagnostic.json', result)
        return
    from winutil import user32
    from runtime import request
    smoke = '--smoke-test' in sys.argv; temporary = None
    if smoke and 'STTS_DATA_DIR' not in os.environ:
        import tempfile
        temporary = tempfile.TemporaryDirectory(prefix='STTS-smoke-'); DATA = Path(temporary.name)
    user32.FindWindowW.restype = __import__('ctypes').wintypes.HWND
    if not smoke and request('status' if '--background-runtime' in sys.argv else 'show') is not None: return
    qt = QApplication(sys.argv); qt.setStyle('Fusion'); qt.setQuitOnLastWindowClosed(False)
    install_qt_translations(qt)
    font = QFont('Malgun Gothic', 10); font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias); qt.setFont(font)
    root = MainWindow()
    control = None
    if not smoke:
        try: control = ControlServer(root)
        except RuntimeError:
            request('status' if '--background-runtime' in sys.argv else 'show'); return
    app = App(root, smoke=smoke)
    if control:
        control.app = app; app.runtime_control = control
    if smoke:
        title = f'STTS smoke {os.getpid()}'
        root.setWindowTitle(localize_message(title))
        assert user32.FindWindowW(None, title), 'The background window cannot be found on a second launch.'
        root.setWindowTitle(tr('STTS'))
    # Installation opens the window even when an existing user prefers hidden startup.
    if smoke or '--show' in sys.argv or not app.config['background'] or not app.config.get('setup_completed'): app.show()
    if smoke:
        def test_flow():
            try:
                ui = DATA / 'ui'; ui.mkdir(exist_ok=True)
                def screenshot(name): QApplication.processEvents(); assert root.grab().save(str(ui / (name + '.png')))
                assert app.footer.isVisible()
                assert not app.microphone_toggle.isChecked() and app.live_microphone.stream is None
                app.microphone_toggle.setChecked(True)  # No input selected: wait without recording.
                assert app.microphone_toggle.isChecked() and app.live_microphone.stream is None
                app.microphone_toggle.setChecked(False)
                app.status.clear()
                screenshot('tts')
                navigation_geometry = app.navigation.geometry()
                assert app.content.geometry() == root.rect()
                app.tts_page.verticalScrollBar().setValue(app.tts_page.verticalScrollBar().maximum())
                screenshot('menu-scroll')
                assert app.navigation.geometry() == navigation_geometry
                pixels = root.grab().toImage(); ratio = pixels.devicePixelRatio()
                assert pixels.pixelColor(round(40 * ratio), round(55 * ratio)).name() == P['card']
                app.tts_page.verticalScrollBar().setValue(0)
                screenshot('bottom-menu')
                pixels = root.grab().toImage(); ratio = pixels.devicePixelRatio()
                assert pixels.pixelColor(round(40 * ratio), round(690 * ratio)).name() == P['card']
                content_geometry = app.content.geometry(); footer_geometry = app.footer.geometry()
                app.tts_busy = True; app.status.setText(tr('음성 생성 중…')); app.update_busy(); QApplication.processEvents()
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
                app.select_tab(3); QApplication.processEvents(); assert app.status.isVisible() and app.status_slot.geometry().bottom() < root.height()
                app.tts_cancel.click(); QApplication.processEvents(); assert not app.tts_busy and not app.status.isVisible()
                app.select_tab(0); QApplication.processEvents()
                assert app.content.geometry() == content_geometry and app.footer.geometry() == footer_geometry
                app.tts_page.verticalScrollBar().setValue(0)
                app.select_tab(1); assert app.tabs.currentWidget() is app.microphone_page and not app.footer.isVisible()
                assert app.microphone_toggle.text() == tr('마이크 함께 보내기')
                app.tools.dismiss(animated=False)
                from microphone_effects import FILTERS
                from microphone_effects import MicrophoneEffects
                import numpy as np
                dry = np.array([0.1, -0.2, 0.0], dtype=np.float32)
                assert np.array_equal(MicrophoneEffects().process(dry), dry)
                assert [app.boxes['microphone_filter'].itemText(i) for i in range(app.boxes['microphone_filter'].count())] == [tr(value) for value in FILTERS]
                app.microphone_pitch_slider.setValue(5); app.boxes['microphone_filter'].setCurrentIndex(app.boxes['microphone_filter'].findData('전화')); app.microphone_strength_slider.setValue(80)
                assert app.live_microphone.effect_settings == (5, '전화', 0.8)
                assert json.loads((DATA / 'settings.json').read_text())['microphone_pitch'] == 5
                screenshot('microphone'); app.reset_microphone_effects()
                assert app.live_microphone.effect_settings == (0, '기본', 0.65) and not app.microphone_strength_slider.isEnabled()
                app.select_tab(2); assert app.tabs.currentWidget() is app.stt_page and not app.footer.isVisible(); screenshot('stt')
                app.select_tab(3); assert app.tabs.currentWidget() is app.settings_page and not app.footer.isVisible()
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
                assert tr('같은 이름의 사운드가 여러 개 있습니다. 사운드보드에서 선택해 주세요.') in app.status.text()
                app.soundboard.clips = []
                app.hide_composer(); app.status.clear()
                app.show_composer()
                field = app.composer.findChild(ComposerEdit)
                QApplication.processEvents()
                assert field.text() == '__duplicate_sound__' and app.config['keep_draft']
                assert app.composer.focusWidget() is field and field.cursorPosition() == len(field.text())
                assert not field.hasSelectedText()
                app.config['keep_draft'] = False; app.hide_composer(); app.show_composer()
                field = app.composer.findChild(ComposerEdit); assert field.text() == ''
                app.config['keep_draft'] = True
                app.tts_busy = True; token = app.audio_stop
                field.setText('queued from composer'); app.submit(field)
                assert app.composer is None and len(app.tts_queue) == 1 and app.audio_stop is token
                app.show_composer(); assert app.composer.findChild(ComposerEdit).text() == ''
                app.hide_composer(); app.cancel_tts(); assert not app.tts_queue
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


if __name__ == '__main__':
    try: main()
    except Exception:
        import traceback
        log = DATA / 'Runtime/startup-error.log'; log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(traceback.format_exc(), encoding='utf-8')
        raise
