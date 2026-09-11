"""STTS Windows UI; the speech engines and stored user data are platform-local."""
import base64
import json
import os
from pathlib import Path
import re
import shutil
import sys
import threading
import time
import urllib.request
import uuid
import webbrowser
from updater import version_tuple

from PySide6.QtCore import Qt, QObject, Signal, Slot, QTimer, QEvent, QSize, QPoint
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QCursor, QKeySequence
from PySide6.QtWidgets import (QApplication, QWidget, QFrame, QLabel, QPushButton, QCheckBox, QComboBox,
    QLineEdit, QPlainTextEdit, QSlider, QScrollArea, QStackedWidget, QVBoxLayout, QHBoxLayout,
    QButtonGroup, QColorDialog, QFileDialog, QMessageBox, QSystemTrayIcon, QMenu, QSizePolicy, QToolTip, QDialog)

VERSION = '0.1.3'
DATA = Path(os.environ.get('STTS_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'STTS')))
DEFAULTS = {'tts': '기본', 'stt': '기본', 'language': 'ko', 'voice': 'Sohee', 'volume': 1.0, 'voice_monitoring': False,
    'caption_alpha': 0.8, 'caption_font': 21, 'caption_color': '#ffffff', 'caption_bg': '#000000',
    'caption_y': 80, 'background': False, 'login': False, 'close': '백그라운드 실행',
    'outside': True, 'shake': True, 'shake_sensitivity': '보통',
    'composer_key': {'keycode': 32, 'modifiers': 3, 'key': 'Space'}, 'stt_key': 'S', 'tts_key': 'V',
    'tts_enabled': True, 'window_bg': '#f7f7f7', 'window_color': '#1f1f1f', 'window_alpha': .95}
TTS_MODELS = {'기본': 'gtts', '낮음': 'supertonic3', '중간': 'qwen06', '높음': 'qwen17'}
STT_MODELS = {'기본': 'turbo', '낮음': 'small', '높음': 'large'}
SPEECH_LANGUAGES = json.loads((Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent / 'Support')) / 'speech_languages.json').read_text(encoding='utf-8'))
STYLE = '''
QWidget { font-family: "Segoe UI"; font-size: 13px; color: #222; }
QWidget#main, QScrollArea, QScrollArea > QWidget > QWidget { background: white; }
QScrollArea { border: none; }
QLabel[heading="true"] { font-weight: 600; }
QLabel[muted="true"] { color: #888; font-size: 12px; }
QPushButton { background: #efefef; border: none; border-radius: 5px; padding: 4px 10px; min-height: 16px; }
QPushButton:hover { background: #e5e5e5; }
QPushButton:pressed { background: #d9d9d9; }
QPushButton:disabled, QComboBox:disabled { color: #aaa; }
QPushButton#nav { text-align: left; background: #fafafa; border-radius: 10px; padding: 14px; }
QPushButton#nav:hover { background: #f0f0f0; }
QFrame#segments { background: #ededed; border-radius: 6px; }
QPushButton#segment { background: transparent; padding: 0; min-height: 0; border-radius: 5px; }
QPushButton#segment:checked { background: #d8d8d8; }
QPushButton#update { background: #087cff; color: white; border-radius: 13px; padding: 0; font-size: 19px; font-weight: 600; }
QLineEdit, QPlainTextEdit { background: white; border: 1px solid #ededed; border-radius: 6px; padding: 4px 7px; selection-background-color: #b9d9ff; }
QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #a9cefa; }
QComboBox { background: #fafafa; border: 1px solid #ddd; border-radius: 5px; padding: 3px 22px 3px 8px; min-height: 18px; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView { background: white; border: 1px solid #ddd; selection-background-color: #d8eaff; }
QSlider::groove:horizontal { background: #ddd; height: 4px; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #1684ff; border-radius: 2px; }
QSlider::handle:horizontal { background: white; border: 1px solid #ccc; width: 13px; height: 13px; margin: -5px 0; border-radius: 7px; }
QCheckBox { spacing: 6px; }
QCheckBox::indicator { width: 13px; height: 13px; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #d0d0d0; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
'''


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def label(text='', heading=False, muted=False):
    result = QLabel(text); result.setWordWrap(True)
    result.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    result.setProperty('heading', heading); result.setProperty('muted', muted)
    return result


def column(parent=None, margins=0, spacing=12):
    layout = QVBoxLayout(parent); layout.setContentsMargins(margins, margins, margins, margins); layout.setSpacing(spacing)
    return layout


def row():
    layout = QHBoxLayout(); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(8)
    return layout


def button(text, callback):
    result = QPushButton(text); result.clicked.connect(lambda: callback()); return result


def divider():
    result = QFrame(); result.setFixedHeight(1); result.setStyleSheet('background: #e6e6e6;'); return result


def icon_for(name):
    image = QPixmap(24, 24); image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor('#007aff'), 1.6))
    if name == '실행':
        painter.drawArc(4, 4, 16, 16, 45 * 16, 270 * 16); painter.drawLine(12, 2, 12, 12)
    elif name == '입력창 동작':
        painter.drawRoundedRect(2, 6, 20, 12, 2, 2)
        for y in (9, 12):
            for x in (6, 10, 14, 18): painter.drawPoint(x, y)
        painter.drawLine(8, 15, 16, 15)
    elif name == '보이스 클론':
        for x, height in [(4, 3), (8, 7), (12, 10), (16, 5), (20, 3)]: painter.drawLine(x, 12 - height, x, 12 + height)
    elif name == '모델 관리':
        painter.drawRoundedRect(3, 5, 18, 14, 2, 2); painter.drawLine(4, 14, 20, 14); painter.drawPoint(17, 16)
    else:
        painter.drawRoundedRect(2, 3, 20, 15, 3, 3); painter.drawLine(6, 18, 6, 22); painter.drawLine(6, 22, 11, 18)
        painter.drawLine(8, 8, 16, 8); painter.drawLine(8, 12, 14, 12)
    painter.end(); return QIcon(image)


class Bridge(QObject):
    dispatch = Signal(object, object)
    def __init__(self, owner, parent):
        super().__init__(parent); self.owner = owner
        self.dispatch.connect(self.deliver, Qt.ConnectionType.QueuedConnection)
    @Slot(object, object)
    def deliver(self, callback, args):
        if self.owner.closing: return
        try: callback(*args)
        except Exception as error: self.owner.status.setText(str(error))


class MainWindow(QWidget):
    def closeEvent(self, event):
        if not hasattr(self, 'owner') or self.owner.closing: event.accept(); return
        event.ignore(); self.owner.close_window()


class ComposerWindow(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.background = QColor(Qt.GlobalColor.transparent)
    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(self.background)
        painter.drawRoundedRect(self.rect(), 9, 9)


class ComposerEdit(QLineEdit):
    submitted = Signal()
    dismissed = Signal()
    def __init__(self):
        super().__init__(); self.preedit = False
    def inputMethodEvent(self, event):
        self.preedit = bool(event.preeditString()); super().inputMethodEvent(event)
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.preedit: super().keyPressEvent(event)
            else: self.submitted.emit()
        elif event.key() == Qt.Key.Key_Escape:
            if self.preedit: super().keyPressEvent(event)
            else: self.dismissed.emit()
        else: super().keyPressEvent(event)


class ShortcutFilter(QObject):
    def __init__(self, owner): super().__init__(owner.root); self.owner = owner
    def eventFilter(self, watched, event):
        owner = self.owner
        if not owner.recording_key: return False
        if event.type() == QEvent.Type.ApplicationDeactivate:
            owner.finish_shortcut(); return False
        if event.type() != QEvent.Type.KeyPress: return False
        if event.key() in (Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift, Qt.Key.Key_Meta): return True
        modifiers = event.modifiers()
        bits = sum(bit for bit, flag in [(2, Qt.KeyboardModifier.ControlModifier), (1, Qt.KeyboardModifier.AltModifier),
                   (4, Qt.KeyboardModifier.ShiftModifier), (8, Qt.KeyboardModifier.MetaModifier)] if modifiers & flag)
        if event.key() == Qt.Key.Key_Escape and not bits: owner.finish_shortcut(); return True
        code = int(event.nativeVirtualKey())
        if not code:
            code = int(event.key()) if int(event.key()) < 256 else 0
            if Qt.Key.Key_F1 <= event.key() <= Qt.Key.Key_F24: code = 0x70 + int(event.key()) - int(Qt.Key.Key_F1)
        if not code or (not bits & 0xB and not 0x70 <= code <= 0x87):
            owner.finish_shortcut(error=ValueError('Ctrl, Alt, Win 또는 기능 키를 포함해 주세요.')); return True
        names = {32: 'Space', 13: 'Enter', 9: 'Tab', 27: 'Esc', 8: 'Backspace', 46: 'Delete'}
        key = names.get(code, QKeySequence(event.key()).toString())
        owner.finish_shortcut({'keycode': code, 'modifiers': bits, 'key': key}); return True


class App:
    def __init__(self, root, smoke=False):
        from winutil import ChildJob
        from audio import Worker
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
        self.voice_cancel = None; self.recording_key = None; self.shortcut_buttons = {}; self.boxes = {}
        self.tts_busy = self.voice_busy = False; self.audio_stop = threading.Event()
        self.backends = {}; self.caption_history = []; self.update_url = None
        self.update_asset = self.update_installer = None
        self.update_checking = self.update_downloading = False
        self.job = ChildJob(); self.tts_worker = Worker(self.job, self.report)
        root.setObjectName('main'); root.setWindowTitle('STTS'); root.setFixedSize(600, 560); root.setStyleSheet(STYLE)
        self.bridge = Bridge(self, root)
        layout = column(root, spacing=12)
        header = row(); header.setContentsMargins(0, 10, 0, 0); header.addStretch()
        segments = QFrame(); segments.setObjectName('segments'); segment_layout = QHBoxLayout(segments)
        segment_layout.setContentsMargins(2, 2, 2, 2); segment_layout.setSpacing(0)
        self.tab_buttons = QButtonGroup(root); self.tab_buttons.setExclusive(True)
        for index, title in enumerate(('TTS', 'STT', '설정')):
            control = QPushButton(title); control.setObjectName('segment'); control.setFixedSize(46, 24); control.setCheckable(True)
            self.tab_buttons.addButton(control, index); segment_layout.addWidget(control)
        self.tab_buttons.idClicked.connect(self.select_tab); self.tab_buttons.button(0).setChecked(True)
        header.addWidget(segments)
        self.update_button = button('↻', self.open_update); self.update_button.setObjectName('update'); self.update_button.setFixedSize(26, 26)
        self.update_button.setToolTip(f'STTS {VERSION} · 업데이트 확인')
        self.update_button.setAccessibleName('업데이트 확인')
        header.addWidget(self.update_button); header.addStretch(); layout.addLayout(header); layout.addWidget(divider())
        self.tabs = QStackedWidget(); layout.addWidget(self.tabs, 1)
        self.status = label('', muted=True); self.status.setContentsMargins(18, 0, 18, 6); self.status.hide(); layout.addWidget(self.status)
        self.status_timer = QTimer(root); self.status_timer.timeout.connect(lambda: self.status.setVisible(bool(self.status.text()))); self.status_timer.start(100)
        self.tts_page, self.tts_layout = self.page(); self.stt_page, self.stt_layout = self.page(); self.settings_page, self.settings_layout = self.page()
        for page in (self.tts_page, self.stt_page, self.settings_page): self.tabs.addWidget(page)
        self.make_tts(); self.make_stt(); self.settings_menu()
        self.shortcut_filter = ShortcutFilter(self); QApplication.instance().installEventFilter(self.shortcut_filter)
        self.caption_timer = QTimer(root); self.caption_timer.setSingleShot(True); self.caption_timer.timeout.connect(self.clear_caption)
        self.composer_timer = QTimer(root); self.composer_timer.timeout.connect(self.composer_tick)
        self.update_busy()
        if not smoke:
            try: self.register_hotkeys()
            except RuntimeError as error: self.status.setText(str(error))
            self.make_tray(); self.start_update_check()
            self.update_timer = QTimer(root); self.update_timer.timeout.connect(self.start_update_check)
            self.update_timer.start(4 * 60 * 60 * 1000)
            if not self.config.get('setup_completed'): QTimer.singleShot(500, self.show_setup)

    def page(self):
        area = QScrollArea(); area.setWidgetResizable(True)
        content = QWidget(); layout = column(content, 18); layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        area.setWidget(content); return area, layout

    def post(self, callback, *args):
        if not self.closing: self.bridge.dispatch.emit(callback, args)
    def report(self, message):
        if message.startswith(('TTS · ', 'STT · ')): self.post(self.backend_changed, message)
        else: self.post(self.status.setText, message)
    def backend_changed(self, message):
        self.backends[message.split(' · ')[0]] = message
        self.status.setText('   /   '.join(self.backends.values()))
    def save(self): write_json(DATA / 'settings.json', self.config)

    def option(self, layout, title, key, values, changed=None):
        line = row(); caption = label(title); caption.setWordWrap(False); caption.setMinimumWidth(64); line.addWidget(caption)
        box = QComboBox(); box.addItems(values); box.setCurrentText(str(self.config[key])); line.addWidget(box, 1)
        def update(value):
            self.config[key] = value; self.save()
            if changed: changed()
        box.currentTextChanged.connect(update); layout.addLayout(line); self.boxes[key] = box
        return box, line

    def check(self, layout, title, key, changed=None):
        control = QCheckBox(title); control.setChecked(bool(self.config[key]))
        def update(enabled):
            try:
                if changed: changed(enabled)
                self.config[key] = enabled; self.save()
            except Exception as error:
                control.blockSignals(True); control.setChecked(self.config[key]); control.blockSignals(False); self.status.setText(str(error))
        control.toggled.connect(update); layout.addWidget(control); return control

    def scale(self, layout, title, key, changed=None):
        line = row(); line.addWidget(label(title))
        slider = QSlider(Qt.Orientation.Horizontal); slider.setRange(0, 100); slider.setValue(round(self.config[key] * 100))
        number = label(f'{slider.value()}%'); number.setFixedWidth(42); number.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        def update(value):
            self.config[key] = value / 100; number.setText(f'{value}%')
            if changed: changed()
        slider.valueChanged.connect(update); slider.sliderReleased.connect(self.save)
        line.addWidget(slider, 1); line.addWidget(number); layout.addLayout(line)

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
                if any(shortcut_data(self.config[k]) == candidate for k in ('composer_key', 'stt_key', 'tts_key') if k != key):
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
            2: (self.config['stt_key'], lambda: self.post(self.toggle_stt)),
            3: (self.config['tts_key'], lambda: self.post(self.tts_enabled.toggle))}, self.report)

    def make_tts(self):
        layout = self.tts_layout
        self.shortcut_row(layout, '입력 단축키', 'composer_key'); layout.addSpacing(10)
        _, line = self.option(layout, '사양', 'tts', list(TTS_MODELS), self.refresh_voices)
        self.tts_enabled = QCheckBox('TTS 사용'); self.tts_enabled.setChecked(self.config['tts_enabled'])
        self.tts_enabled.toggled.connect(self.toggle_tts_changed); line.addWidget(self.tts_enabled)
        self.voice_row = QWidget(); voice_layout = row(); self.voice_row.setLayout(voice_layout)
        caption = label('목소리'); caption.setMinimumWidth(64); voice_layout.addWidget(caption)
        self.voice_box = QComboBox(); voice_layout.addWidget(self.voice_box, 1); layout.addWidget(self.voice_row)
        self.voice_box.currentIndexChanged.connect(self.voice_changed)
        language_row = row(); caption = label('언어'); caption.setMinimumWidth(64); language_row.addWidget(caption)
        self.language_box = QComboBox(); language_row.addWidget(self.language_box, 1); layout.addLayout(language_row)
        self.language_box.currentIndexChanged.connect(self.language_changed)
        self.refresh_voices(); self.scale(layout, '음량', 'volume')
        self.voice_monitoring = self.check(layout, '목소리 모니터링', 'voice_monitoring')
        self.voice_monitoring.setToolTip('전송하는 TTS 목소리를 기본 스피커·헤드폰에서도 함께 듣습니다.')
        self.surface_controls(layout, '입력창 모양', 'window')
        self.tts_cancel = button('취소', self.cancel_tts); layout.addWidget(self.tts_cancel, alignment=Qt.AlignmentFlag.AlignRight); self.tts_cancel.hide()
        connection = row(); connection.addWidget(label('가상 마이크', muted=True)); connection.addStretch()
        connection.addWidget(button('처음 설정', self.show_setup)); layout.addLayout(connection)

    def show_setup(self):
        dialog = QDialog(self.root); dialog.setObjectName('main'); dialog.setWindowTitle('STTS 처음 설정'); dialog.setFixedWidth(520)
        layout = column(dialog, 24, 16)
        title = label('STTS 처음 설정', heading=True); title.setStyleSheet('font-size: 18px; font-weight: 600;'); layout.addWidget(title)
        for title, text in [
            ('1. Discord 연결', 'Discord → 설정 → 음성 및 비디오 → 입력 장치에서 STTS를 선택하세요.\n\n출력 장치는 평소 사용하는 헤드셋·스피커를 선택하세요.'),
            ('2. 문장 보내기', 'STTS에서 TTS 사용을 켜고 입력 단축키로 입력창을 열어 문장을 보내세요.'),
            ('3. 설정에서 더 보기', '보이스 클론: 음성을 등록해 원하는 목소리로 말할 수 있습니다.\nTTS 단축어: 자주 쓰는 문장을 짧은 단축어로 보낼 수 있습니다.'),
        ]:
            section = column(spacing=10); section.addWidget(label(title, heading=True)); section.addWidget(label(text)); layout.addLayout(section)
        def done():
            self.config['setup_completed'] = True; self.save(); dialog.accept()
        line = row(); line.addStretch(); start = button('사용 시작', done)
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
        presets = ['Google 기본'] if tier == '기본' else ([f'{g}{i}' for g in ('F', 'M') for i in range(1, 6)] if tier == '낮음'
                   else ['Sohee', 'Vivian', 'Serena', 'Uncle_Fu', 'Dylan', 'Eric', 'Ryan', 'Aiden', 'Ono_Anna'])
        for name in presets: self.voice_box.addItem(name, 'preset:' + name)
        if tier in ('중간', '높음'):
            for profile in self.profiles:
                self.voice_box.addItem(profile['name'] or '이름·대본 필요', 'clone:' + profile['id'])
                self.voice_box.model().item(self.voice_box.count() - 1).setEnabled(bool(profile['name'].strip() and profile['transcript'].strip()))
        selected = 'clone:' + self.config['selected_clone_id'] if tier in ('중간', '높음') and self.config.get('selected_clone_id') else 'preset:' + self.config['voice']
        index = self.voice_box.findData(selected)
        if index < 0: index = 0; self.config['voice'] = presets[0]
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
        names = {'ko': '한국어', 'en': '영어', 'ja': '일본어', 'zh': '중국어', 'de': '독일어', 'fr': '프랑스어', 'es': '스페인어', 'it': '이탈리아어', 'pt': '포르투갈어', 'ru': '러시아어'}
        codes = SPEECH_LANGUAGES[key]; self.language_box.blockSignals(True); self.language_box.clear()
        for code in sorted(codes, key=lambda c: ({'ko': 0, 'en': 1, 'ja': 2}.get(c, 3), c)):
            self.language_box.addItem(f'{names.get(code, codes[code])} · {code}', code)
        if self.config['language'] not in codes: self.config['language'] = 'ko'
        self.language_box.setCurrentIndex(self.language_box.findData(self.config['language'])); self.language_box.blockSignals(False)
    def language_changed(self, index):
        self.config['language'] = self.language_box.itemData(index); self.save()

    def surface_controls(self, layout, title, prefix):
        layout.addSpacing(10); layout.addWidget(label(title, heading=True)); layout.addSpacing(4)
        colors = row()
        for text, suffix in [('배경', 'bg'), ('글자', 'color')]:
            control = button(text, lambda key=prefix + '_' + suffix: self.pick_color(key)); colors.addWidget(control)
        colors.addStretch(); layout.addLayout(colors)
        self.scale(layout, '불투명도', prefix + '_alpha', self.refresh_surfaces)
        preview = QLabel('음성 입력창 미리보기' if prefix == 'window' else '자막 미리보기')
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter); preview.setMinimumHeight(44 if prefix == 'window' else 56)
        setattr(self, prefix + '_preview', preview); layout.addWidget(preview); self.refresh_surfaces()
    def rgba(self, prefix):
        color = QColor(self.config[prefix + '_bg'])
        return f'rgba({color.red()}, {color.green()}, {color.blue()}, {round(self.config[prefix + "_alpha"] * 255)})'
    def refresh_surfaces(self):
        for prefix in ('window', 'caption'):
            preview = getattr(self, prefix + '_preview', None)
            if preview:
                preview.setStyleSheet(f'background: {self.rgba(prefix)}; color: {self.config[prefix + "_color"]}; border-radius: 8px; font-size: {13 if prefix == "window" else 21}px;')
        if self.composer:
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
        text = widget.text().strip(); text = self.config.get('tts_phrases', {}).get(text, text)
        if not self.tts_enabled.isChecked(): self.status.setText('TTS를 켜세요.'); return
        if self.tts_busy or self.voice_busy: self.status.setText('현재 음성 작업이 끝난 후 다시 전송하세요.'); return
        if not 1 <= len(text) <= 500: self.status.setText('1~500자를 입력하세요.'); return
        from audio import cable_output
        try: cable_output(refresh=True)
        except Exception as error:
            self.status.setText(str(error))
            QToolTip.showText(widget.mapToGlobal(QPoint(0, widget.height() + 10)), str(error), widget, msecShowTime=10000)
            return
        request = {'action': 'tts', 'text': text, 'root': str(self.model_root), 'language': self.config['language'], 'voice': self.config['voice']}
        model = TTS_MODELS[self.config['tts']]
        profile = next((p for p in self.profiles if p['id'] == self.config.get('selected_clone_id')), None) if model.startswith('qwen') else None
        if profile and (not profile['name'].strip() or not 1 <= len(profile['transcript'].strip()) <= 1000):
            self.status.setText('설정 > 보이스 클론에서 선택한 목소리의 이름과 대본을 확인해 주세요.'); return
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
                    self.report('가상 마이크로 보내는 중…')
                    warning = play_cable(np.frombuffer(base64.b64decode(result['audio']), dtype='<f4'), result['rate'], lambda: self.config['volume'], token, monitor=monitoring)
                self.post(self.finish_tts, token, warning or '')
            except Exception as error:
                if not token.is_set(): self.post(self.finish_tts, token, str(error))
        threading.Thread(target=run, daemon=True).start()
    def finish_tts(self, token, message):
        if token is not self.audio_stop: return
        self.tts_busy = False; self.status.setText(message or '   /   '.join(self.backends.values())); self.update_busy()
        worker = self.tts_worker
        def release():
            if self.closing or self.tts_busy or self.audio_stop is not token or self.tts_worker is not worker: return
            from audio import Worker
            worker.stop(); self.tts_worker = Worker(self.job, self.report)
        QTimer.singleShot(30000, release)
    def cancel_tts(self):
        from audio import Worker
        self.audio_stop.set(); self.tts_worker.stop(); self.tts_worker = Worker(self.job, self.report)
        self.tts_busy = False; self.status.clear(); self.update_busy()

    def show_composer(self):
        if not self.tts_enabled.isChecked(): return
        if self.composer: self.hide_composer(); return
        from winutil import user32
        self.previous_window = user32.GetForegroundWindow()
        window = ComposerWindow()
        layout = QHBoxLayout(window); layout.setContentsMargins(12, 10, 12, 10)
        field = ComposerEdit(); field.setPlaceholderText('입력 후 Enter'); layout.addWidget(field)
        field.submitted.connect(lambda: self.submit(field)); field.dismissed.connect(self.hide_composer)
        point = QCursor.pos(); screen = QApplication.screenAt(point) or QApplication.primaryScreen(); area = screen.availableGeometry()
        width, height = min(480, area.width() - 16), 44
        x = min(max(point.x() + 14, area.left() + 8), area.right() - width - 7)
        y = min(max(point.y() + 14, area.top() + 8), area.bottom() - height - 7)
        window.setGeometry(x, y, width, height); self.composer = window; self.refresh_surfaces()
        window.show(); window.raise_(); window.activateWindow(); field.setFocus()
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
        layout = self.stt_layout; self.shortcut_row(layout, '자막 단축키', 'stt_key'); layout.addSpacing(10)
        _, line = self.option(layout, '사양', 'stt', list(STT_MODELS), self.stt_model_changed)
        self.stt_enabled = QCheckBox('STT 사용'); self.stt_enabled.clicked.connect(self.toggle_stt); line.addWidget(self.stt_enabled)
        self.history = QLabel(); self.history.setWordWrap(True); self.history.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.history.hide(); layout.addWidget(self.history)
        self.surface_controls(layout, '자막 모양', 'caption')
    def stt_model_changed(self):
        if self.capture: self.stop_stt(); self.toggle_stt()
    def toggle_stt(self):
        if self.capture: self.stop_stt(); return
        if self.voice_busy: self.stt_enabled.setChecked(False); self.status.setText('목소리 저장이 끝난 뒤 STT를 켜세요.'); return
        from audio import Capture, Worker
        capture = Capture(self.job, Worker(self.job, self.report), STT_MODELS[self.config['stt']], self.model_root,
                          lambda text: self.post(self.show_caption, text), self.report, lambda: self.post(self.capture_ended, capture))
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
            self.caption_history = (self.caption_history + [text])[-100:]
            self.history.setText('\n\n'.join(self.caption_history)); self.history.show()
            self.history.setStyleSheet(f'background: {self.rgba("caption")}; color: {self.config["caption_color"]}; border-radius: 8px; padding: 12px;')
        if not self.caption:
            self.caption = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
            self.caption.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground); self.caption.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            layout = column(self.caption, 0, 0); self.caption_label = QLabel(); self.caption_label.setWordWrap(True)
            self.caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter); layout.addWidget(self.caption_label)
            self.caption.show()
            from winutil import clickthrough
            clickthrough(self.caption)
        self.caption_label.setText('\n'.join(self.caption_history[-2:]) if text else '')
        self.style_caption(); self.caption_timer.start(10000)
    def clear_caption(self):
        if self.caption: self.caption_label.clear(); self.style_caption()
    def style_caption(self):
        if not self.caption: return
        screen = self.root.screen() or QApplication.primaryScreen(); area = screen.availableGeometry()
        width = min(1000, area.width() - 80)
        self.caption_label.setStyleSheet(f'background: {self.rgba("caption")}; color: {self.config["caption_color"]}; font-size: {int(self.config["caption_font"])}px; border-radius: 8px; padding: 14px 20px;')
        self.caption.setFixedWidth(width); self.caption_label.setFixedWidth(width)
        height = max(60, self.caption_label.heightForWidth(width), self.caption_label.sizeHint().height())
        height = min(height, area.height() - 40)
        self.caption.setFixedHeight(height)
        self.caption.move(area.left() + (area.width() - width) // 2, max(area.top() + 20, area.bottom() - int(self.config['caption_y']) - height))

    def select_tab(self, index):
        if self.recording_key: self.finish_shortcut()
        if self.voice_cancel: self.voice_cancel()
        self.tabs.setCurrentIndex(index); self.tab_buttons.button(index).setChecked(True)
    def clear_settings(self, title=None):
        if self.voice_cancel: self.voice_cancel()
        def clear(layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().hide(); item.widget().deleteLater()
                elif item.layout():
                    clear(item.layout()); item.layout().deleteLater()
        clear(self.settings_layout)
        if title:
            header = row(); header.addWidget(button('‹ 설정', self.settings_menu)); header.addWidget(label(title, heading=True)); header.addStretch()
            self.settings_layout.addLayout(header); self.settings_layout.addWidget(divider()); self.settings_layout.addSpacing(4)
        return self.settings_layout
    def settings_menu(self):
        layout = self.clear_settings(); title = label('설정', heading=True); title.setStyleSheet('font-size: 20px; font-weight: 600;'); layout.addWidget(title)
        for name, callback in [('실행', self.settings_run), ('입력창 동작', self.settings_input), ('TTS 단축어', self.settings_phrases), ('보이스 클론', self.settings_voices), ('모델 관리', self.settings_models)]:
            control = QPushButton(); control.setObjectName('nav'); control.setFixedHeight(52)
            content = QHBoxLayout(control); content.setContentsMargins(14, 0, 14, 0); content.setSpacing(14)
            image = QLabel(); image.setPixmap(icon_for(name).pixmap(24, 24)); image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            text = label(name, heading=True); text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            arrow = label('›', muted=True); arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            content.addWidget(image); content.addWidget(text); content.addStretch(); content.addWidget(arrow)
            control.clicked.connect(lambda checked=False, fn=callback: fn()); layout.addWidget(control)
        line = row(); line.addWidget(label(f'STTS {VERSION}', muted=True)); line.addStretch()
        line.addWidget(button('업데이트 확인', lambda: self.start_update_check(manual=True)))
        layout.addLayout(line)
        layout.addWidget(button('가상 마이크 연결 점검', self.check_microphone))
    def settings_run(self):
        from winutil import set_login
        layout = self.clear_settings('실행'); self.check(layout, '로그인 시 자동 실행', 'login', set_login)
        self.check(layout, '시작 시 백그라운드 실행', 'background'); self.option(layout, '창 닫을 때', 'close', ['백그라운드 실행', '최소화', '앱 종료'])
    def settings_input(self):
        layout = self.clear_settings('입력창 동작'); layout.addWidget(label('입력창 닫기', heading=True))
        self.check(layout, '입력창 밖을 클릭하면 닫기', 'outside')
        self.check(layout, '마우스를 흔들면 닫기', 'shake', lambda enabled: self.boxes['shake_sensitivity'].setEnabled(enabled))
        self.option(layout, '흔들기 민감도', 'shake_sensitivity', ['낮음', '보통', '높음']); self.boxes['shake_sensitivity'].setEnabled(self.config['shake'])
    def save_tts_phrase(self, shortcut, phrase, original=None):
        shortcut, phrase = shortcut.strip(), phrase.strip()
        if not 1 <= len(shortcut) <= 500 or not 1 <= len(phrase) <= 500: raise ValueError('단축어와 읽을 문장은 각각 1~500자로 입력해 주세요.')
        phrases = dict(self.config.get('tts_phrases', {}))
        if shortcut != original and shortcut in phrases: raise ValueError('이미 저장된 단축어입니다. 기존 항목을 수정해 주세요.')
        if original is not None: phrases.pop(original, None)
        phrases[shortcut] = phrase; self.config['tts_phrases'] = phrases; self.save()
    def delete_tts_phrase(self, shortcut): self.config.get('tts_phrases', {}).pop(shortcut, None); self.save()
    def settings_phrases(self, original=None):
        layout = self.clear_settings('TTS 단축어'); layout.addWidget(label('단축어', heading=True))
        shortcut = QLineEdit(original or ''); shortcut.setAccessibleName('단축어'); layout.addWidget(shortcut)
        layout.addWidget(label('읽을 문장', heading=True)); phrase = QPlainTextEdit(); phrase.setFixedHeight(64); phrase.setAccessibleName('읽을 문장')
        if original is not None: phrase.setPlainText(self.config['tts_phrases'][original])
        layout.addWidget(phrase); error = label(); error.setStyleSheet('color: #c33;'); error.hide()
        def save():
            try: self.save_tts_phrase(shortcut.text(), phrase.toPlainText(), original)
            except (ValueError, OSError) as reason: error.setText(str(reason)); error.show(); return
            self.settings_phrases()
        controls = row(); controls.addWidget(button('추가' if original is None else '저장', save))
        if original is not None: controls.addWidget(button('취소', self.settings_phrases))
        controls.addStretch(); layout.addLayout(controls); layout.addWidget(error); layout.addWidget(divider())
        if not self.config.get('tts_phrases'): layout.addWidget(label('저장된 단축어 없음', muted=True))
        def delete(key):
            try: self.delete_tts_phrase(key)
            except OSError as reason: error.setText(str(reason)); error.show(); return
            self.settings_phrases()
        for key, value in sorted(self.config.get('tts_phrases', {}).items()):
            line = row(); detail = column(); detail.addWidget(label(key, heading=True)); detail.addWidget(label(value, muted=True)); line.addLayout(detail, 1)
            line.addWidget(button('수정', lambda k=key: self.settings_phrases(k))); line.addWidget(button('삭제', lambda k=key: delete(k))); layout.addLayout(line)

    def settings_voices(self):
        layout = self.clear_settings('보이스 클론'); controls = row(); controls.addWidget(button('파일 추가', self.add_voice_files)); controls.addWidget(button('마이크 녹음', self.add_voice)); controls.addStretch(); layout.addLayout(controls)
        if not self.profiles: layout.addWidget(label('저장된 목소리 없음', muted=True))
        for profile in self.profiles:
            control = button((profile['name'] or '이름·대본 필요') + '  ›', lambda p=profile: self.edit_voice(p)); control.setObjectName('nav'); layout.addWidget(control)
    def save_profiles(self): write_json(self.voice_root / 'profiles.json', self.profiles); self.refresh_voices()
    def edit_voice(self, profile):
        if self.tts_busy or self.voice_busy: self.status.setText('음성 작업이 끝난 뒤 수정하세요.'); return
        layout = self.clear_settings('보이스 클론'); layout.addWidget(button('‹ 목록', self.settings_voices), alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(label('목소리명', heading=True)); name = QLineEdit(profile['name']); layout.addWidget(name)
        layout.addWidget(label('대본', heading=True)); transcript = QPlainTextEdit(profile['transcript']); transcript.setFixedHeight(110); layout.addWidget(transcript)
        state = label('', muted=True)
        def save():
            text = transcript.toPlainText().strip(); value = name.text().strip()
            if len(text) > 1000: state.setText('대본은 1,000자 이내로 입력해 주세요.'); return
            if any(p['id'] != profile['id'] and p['name'] == value for p in self.profiles): state.setText('이미 사용 중인 목소리명입니다.'); return
            profile.update(name=value, transcript=text); self.save_profiles(); state.setText('등록 완료' if value and text else '이름·대본 필요')
        name.textChanged.connect(save); transcript.textChanged.connect(save)
        line = row(); line.addWidget(state, 1); line.addWidget(button('삭제', lambda: self.delete_voice(profile))); layout.addLayout(line)
        state.setText('등록 완료' if profile['name'] and profile['transcript'] else '이름·대본 필요')
    def delete_voice(self, profile):
        if self.tts_busy or self.voice_busy: self.status.setText('음성 작업이 끝난 뒤 삭제하세요.'); return
        if QMessageBox.question(self.root, '목소리 삭제', f"{profile['name']} 목소리를 삭제할까요?") != QMessageBox.StandardButton.Yes: return
        from send2trash import send2trash
        path = self.voice_root / (profile['id'] + '.wav')
        if path.exists(): send2trash(str(path))
        self.profiles.remove(profile); self.save_profiles(); self.settings_voices()
    def add_voice_files(self):
        if self.tts_busy or self.voice_busy or self.capture: self.status.setText('TTS와 STT를 멈춘 뒤 목소리를 추가하세요.'); return
        paths, _ = QFileDialog.getOpenFileNames(self.root, '목소리 추가', '', '음성 파일 (*.mp3 *.wav *.m4a *.aiff *.aif)')
        if not paths: return
        self.voice_busy = True; self.update_busy()
        def run():
            for index, path in enumerate(paths): self.store_voice((Path(path).stem, ''), None, path, more=index < len(paths) - 1)
        threading.Thread(target=run, daemon=True).start()
    def add_voice(self):
        if self.tts_busy or self.voice_busy or self.capture: self.status.setText('TTS와 STT를 멈춘 뒤 목소리를 추가하세요.'); return
        import sounddevice as sd
        layout = self.clear_settings('보이스 클론'); layout.addWidget(button('‹ 목록', self.settings_voices), alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(label('대본 (선택)', heading=True)); transcript = QPlainTextEdit(); transcript.setFixedHeight(100); layout.addWidget(transcript)
        mic = QComboBox()
        for index, device in enumerate(sd.query_devices()):
            if device['max_input_channels'] > 0 and 'CABLE' not in device['name'].upper() and sd.query_hostapis(device['hostapi'])['name'] == 'Windows WASAPI': mic.addItem(device['name'], index)
        layout.addWidget(mic); hint = label('', muted=True); layout.addWidget(hint)
        state = {'stream': None, 'chunks': [], 'count': 0, 'start': 0}
        timer = QTimer(self.root)
        def stop_recording():
            timer.stop()
            if state['stream']: state['stream'].abort(); state['stream'].close(); state['stream'] = None
            self.voice_busy = False; self.update_busy()
        def cancel():
            stop_recording(); timer.deleteLater(); self.voice_cancel = None
        self.voice_cancel = cancel
        def record():
            import numpy as np
            if state['stream']:
                state['stream'].stop(); state['stream'].close(); state['stream'] = None; timer.stop()
                data = np.concatenate(state['chunks']) if state['chunks'] else np.zeros(0, dtype='float32')
                if not 3 <= len(data) / 24000 <= 30: hint.setText('3초 이상 녹음하세요.'); control.setText('녹음 시작'); return
                details = ('녹음한 목소리', transcript.toPlainText().strip()); self.voice_cancel = None; timer.deleteLater()
                control.setEnabled(False); hint.setText('목소리 저장 중…')
                threading.Thread(target=self.store_voice, args=(details, data, None), daemon=True).start(); return
            try:
                if mic.currentIndex() < 0: raise ValueError('사용 가능한 물리 마이크가 없습니다.')
                state.update(chunks=[], count=0, start=time.monotonic())
                def callback(indata, frames, timestamp, status):
                    remaining = 24000 * 30 - state['count']
                    if remaining > 0: state['chunks'].append(indata[:remaining, 0].copy()); state['count'] += min(frames, remaining)
                state['stream'] = sd.InputStream(device=mic.currentData(), samplerate=24000, channels=1, dtype='float32', callback=callback, extra_settings=sd.WasapiSettings(auto_convert=True))
                state['stream'].start(); self.voice_busy = True; self.update_busy(); control.setText('녹음 완료'); timer.start(100)
            except Exception as error: hint.setText(str(error)); stop_recording()
        def tick():
            seconds = time.monotonic() - state['start']; hint.setText(f'녹음 중… {seconds:.1f} / 30초')
            if seconds >= 30: record()
        timer.timeout.connect(tick); control = button('녹음 시작', record); layout.addWidget(control, alignment=Qt.AlignmentFlag.AlignLeft)
    def store_voice(self, details, data, path, more=False):
        from audio import Worker
        import numpy as np
        import soundfile as sf
        from scipy.signal import resample_poly
        worker = Worker(self.job, self.report)
        try:
            name, transcript = details
            if path:
                result = worker.request({'action': 'decode', 'path': path}); data = np.frombuffer(base64.b64decode(result['audio']), dtype='<f4')
            if not 3 <= len(data) / 24000 <= 30 or not np.isfinite(data).all() or np.max(np.abs(data)) < .005: raise ValueError('목소리가 들리는 3~30초 샘플이 필요합니다.')
            if not transcript:
                self.report('샘플 대본을 로컬에서 인식하는 중…'); pcm = resample_poly(data, 2, 3).astype('<f4')
                result = worker.request({'action': 'stt', 'model': 'small', 'root': str(self.model_root), 'audio': base64.b64encode(pcm.tobytes()).decode()}); transcript = result['text']
                if not transcript: raise ValueError('대본을 인식하지 못했습니다. 대본을 직접 입력하세요.')
            ident = uuid.uuid4().hex; sf.write(self.voice_root / (ident + '.wav'), data, 24000, subtype='PCM_16')
            self.post(self.finish_voice, {'id': ident, 'name': name, 'transcript': transcript}, None, more)
        except Exception as error: self.post(self.finish_voice, None, str(error), more)
        finally: worker.stop()
    def finish_voice(self, profile, error, more=False):
        self.voice_busy = more; self.update_busy()
        if error:
            self.status.setText(error)
            if not more: self.settings_voices()
            return
        name, number = profile['name'], 2
        while any(p['name'] == profile['name'] for p in self.profiles): profile['name'] = f'{name} ({number})'; number += 1
        self.profiles.append(profile); self.save_profiles(); self.status.clear()
        if not more: self.edit_voice(profile)

    def settings_models(self):
        layout = self.clear_settings('모델 관리'); header = row(); header.addWidget(label('다운로드한 모델', heading=True), 1)
        header.addWidget(button('폴더 열기', lambda: os.startfile(self.model_root))); header.addWidget(button('새로고침', self.settings_models)); layout.addLayout(header)
        catalog = json.loads((Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'models.json').read_text(encoding='utf-8'))
        current = {f"{key}-{asset.get('variant', asset['revision'][:12])}": asset for key, asset in catalog.items()}
        layout.addWidget(label('사용하지 않는 모델을 삭제해 저장 공간을 확보할 수 있습니다.', muted=True))
        layout.addWidget(label(str(self.model_root), muted=True)); paths = sorted(p for p in self.model_root.iterdir() if p.is_dir())
        if not paths: layout.addWidget(label('다운로드한 모델이 없습니다.', muted=True))
        names = {'turbo': 'Whisper large-v3-turbo', 'small': 'Whisper small', 'large': 'Whisper large-v3', 'supertonic3': 'Supertonic 3',
                 'qwen06Custom': 'Qwen3-TTS 0.6B CustomVoice', 'qwen17Custom': 'Qwen3-TTS 1.7B CustomVoice', 'qwen06': 'Qwen3-TTS 0.6B Base', 'qwen17': 'Qwen3-TTS 1.7B Base'}
        for path in paths:
            size = sum(f.stat().st_size for f in path.rglob('*') if f.is_file()); line = row(); details = column(spacing=4)
            asset = current.get(path.name)
            state = ('INT8 · 일부 구성요소 원본 정밀도' if path.name.startswith(('qwen', 'supertonic')) else 'INT8') if asset else '이전 버전 · 현재 사용하지 않음'
            details.addWidget(label(names.get(path.name.split('-')[0], path.name.split('-')[0]))); details.addWidget(label(f'{size / 1024**3:.2f} GB · {state}', muted=True)); line.addLayout(details, 1)
            control = button('삭제', lambda p=path: self.delete_model(p)); control.setEnabled(not (self.tts_busy or self.voice_busy or self.capture)); line.addWidget(control); layout.addLayout(line)
    def delete_model(self, path):
        if self.tts_busy or self.capture or self.voice_busy: self.status.setText('음성 작업을 모두 멈춘 뒤 삭제하세요.'); return
        if path.parent != self.model_root or path.is_symlink(): return
        if QMessageBox.question(self.root, '모델을 삭제할까요?', f'{path.name}\n다음 사용 시 다시 다운로드합니다.') != QMessageBox.StandardButton.Yes: return
        self.cancel_tts(); shutil.rmtree(path); self.settings_models()
    def update_busy(self):
        self.update_button.setEnabled(not (self.tts_busy or self.capture or self.voice_busy or self.update_checking or self.update_downloading))
        enabled = self.tts_enabled.isChecked() and not self.tts_busy
        self.boxes['tts'].setEnabled(enabled); self.voice_box.setEnabled(enabled); self.language_box.setEnabled(enabled)
        self.voice_monitoring.setEnabled(enabled)
        self.boxes['stt'].setEnabled(not self.capture); self.tts_cancel.setVisible(self.tts_busy)
    def start_update_check(self, manual=False):
        if self.update_checking or self.update_downloading: return
        self.update_checking = True; self.update_busy()
        if manual: self.status.setText('업데이트 확인 중…')
        threading.Thread(target=lambda: self.check_update(manual), daemon=True).start()
    def check_update(self, manual=False):
        try:
            from updater import check_update
            self.post(self.update_checked, check_update(VERSION), '', manual)
        except Exception as error:
            self.post(self.update_checked, None, str(error), manual)
    def update_checked(self, asset, error, manual):
        self.update_checking = False
        if error:
            self.status.setText('업데이트 확인 실패 · ' + error)
            self.update_button.setToolTip('업데이트 확인 실패 · 클릭하여 다시 시도')
        else:
            if asset != self.update_asset: self.update_installer = None
            self.update_asset = asset
            self.update_url = asset['browser_download_url'] if asset else None
            self.update_button.setText('↓' if asset else '↻')
            message = f'STTS {asset["version"]} 다운로드' if asset else f'최신 Windows 버전입니다. · {VERSION}'
            self.update_button.setToolTip(message); self.update_button.setAccessibleName(message)
            if manual or asset: self.status.setText(message)
        self.update_busy()
    def open_update(self):
        if self.tts_busy or self.capture or self.voice_busy or self.update_checking or self.update_downloading: return
        if self.update_installer and self.composer:
            self.status.setText('입력창을 닫은 뒤 업데이트를 설치하세요.'); return
        if not self.update_asset: self.start_update_check(manual=True); return
        if self.update_installer:
            try: os.startfile(str(self.update_installer))
            except OSError as error: self.status.setText('설치 프로그램 실행 실패 · ' + str(error)); return
            self.quit(); return
        self.update_downloading = True; self.update_busy(); self.status.setText('업데이트 다운로드 중…')
        asset = dict(self.update_asset)
        def download():
            try:
                from updater import download_installer
                previous = -1
                def progress(size, total):
                    nonlocal previous
                    percent = int(size * 100 / max(total, 1))
                    if percent != previous:
                        previous = percent; self.report(f'업데이트 다운로드 중… {percent}%')
                path = download_installer(asset, DATA / 'Updates', VERSION, progress)
                self.post(self.update_downloaded, path, '')
            except Exception as error: self.post(self.update_downloaded, None, str(error))
        threading.Thread(target=download, daemon=True).start()
    def update_downloaded(self, path, error):
        self.update_downloading = False; self.update_installer = path
        if error: self.status.setText('업데이트 다운로드 실패 · ' + error)
        else:
            self.status.setText('다운로드·검증 완료 · 파란 버튼을 누르면 업데이트를 설치합니다.')
            self.update_button.setToolTip('업데이트 설치 후 STTS 종료'); self.update_button.setAccessibleName('업데이트 설치')
        self.update_busy()
    def make_tray(self):
        self.tray = QSystemTrayIcon(icon_for('TTS 단축어'), self.root); self.tray.setToolTip('STTS'); menu = QMenu()
        for title, callback in [('STTS 열기', self.show), ('입력창 열기', self.show_composer), ('종료', self.quit)]: menu.addAction(title).triggered.connect(callback)
        self.tray.setContextMenu(menu); self.tray.activated.connect(lambda reason: self.show() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show(); self.tray_menu = menu
    def show(self): self.root.showNormal(); self.root.raise_(); self.root.activateWindow()
    def close_window(self):
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
    if singleton.duplicate and not smoke:
        user32.FindWindowW.restype = __import__('ctypes').wintypes.HWND
        hwnd = user32.FindWindowW(None, 'STTS')
        if hwnd: user32.ShowWindow(hwnd, 9); user32.SetForegroundWindow(hwnd)
        return
    qt = QApplication(sys.argv); qt.setStyle('Fusion'); qt.setQuitOnLastWindowClosed(False)
    font = QFont('Segoe UI', 10); font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias); qt.setFont(font)
    root = MainWindow(); app = App(root, smoke=smoke)
    # Installation opens the window even when an existing user prefers hidden startup.
    if smoke or '--show' in sys.argv or not app.config['background']: app.show()
    if smoke:
        def test_flow():
            try:
                ui = DATA / 'ui'; ui.mkdir(exist_ok=True)
                def screenshot(name): QApplication.processEvents(); assert root.grab().save(str(ui / (name + '.png')))
                screenshot('tts'); app.select_tab(1); screenshot('stt'); app.select_tab(2)
                for name, show in [('settings', app.settings_menu), ('input', app.settings_input), ('phrases', app.settings_phrases),
                                   ('voices', app.settings_voices), ('models', app.settings_models), ('runtime', app.settings_run)]: show(); screenshot(name)
                app.select_tab(0); app.show_setup(); app.check_microphone()
                original_background = app.config['window_bg'], app.config['window_alpha']
                app.config.update(window_bg='#1464c8', window_alpha=.6)
                app.show_composer(); assert app.composer.isVisible(); QApplication.processEvents()
                frame = app.composer.grab(); pixels = frame.toImage(); ratio = pixels.devicePixelRatio()
                actual = pixels.pixelColor(round(240 * ratio), round(5 * ratio)).getRgb()
                assert all(abs(value - expected) <= 2 for value, expected in zip(actual, (20, 100, 200, 153))), actual
                assert pixels.pixelColor(0, 0).alpha() == 0
                frame.save(str(ui / 'composer.png')); app.hide_composer()
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
