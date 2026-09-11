"""Reusable Qt controls, input windows, and keyboard event handling."""
from PySide6.QtCore import Qt, QObject, Signal, Slot, QEvent
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QKeySequence
from PySide6.QtWidgets import QCheckBox, QWidget, QFrame, QLabel, QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout, QSizePolicy, QGraphicsDropShadowEffect


STYLE = '''
QWidget { font-family: "Malgun Gothic", "Segoe UI"; font-size: 13px; color: #333d4b; }
QWidget#main, QScrollArea, QScrollArea > QWidget > QWidget { background: #f5f6f8; }
QScrollArea { border: none; }
QFrame#card { background: white; border: none; border-radius: 18px; }
QLabel[heading="true"] { font-weight: 600; font-size: 15px; }
QLabel[muted="true"] { color: #6b7684; font-size: 13px; }
QPushButton { background: #edf0f4; border: none; border-radius: 8px; padding: 7px 12px; min-height: 18px; }
QPushButton:hover { background: #e4e8ed; }
QPushButton:pressed { background: #d9dfe7; }
QPushButton:focus { outline: 1px solid #3182f6; }
QPushButton:disabled, QComboBox:disabled { color: #aeb6c0; }
QPushButton#nav { text-align: left; background: white; border-radius: 18px; padding: 20px; }
QPushButton#nav:hover { background: #eaf2ff; }
QFrame#toolsOverlay { background: transparent; }
QPushButton#toolBackdrop { background: rgba(0, 0, 0, 40); border-radius: 0; }
QFrame#toolDrawer { background: #f5f6f8; border-top-left-radius: 24px; border-top-right-radius: 24px; }
QFrame#segments { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255,255,255,235), stop:1 rgba(230,237,247,180)); border: 1px solid rgba(255,255,255,245); border-radius: 20px; }
QPushButton#segment { background: transparent; padding: 0; min-height: 0; border-radius: 16px; color: #6b7684; font-weight: 600; }
QPushButton#segment:checked { background: rgba(209,218,231,130); color: #191f28; }
QPushButton#segment:focus { border: 1px solid #8ab6f5; outline: none; }
QLineEdit, QPlainTextEdit { background: white; border: 1px solid #e5e8ec; border-radius: 10px; padding: 8px 10px; selection-background-color: #c9e0ff; }
QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #3182f6; }
QComboBox { background: #f5f6f8; border: none; border-radius: 8px; padding: 6px 24px 6px 10px; min-height: 20px; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: white; border: 1px solid #e5e8ec; selection-background-color: #eaf2ff; selection-color: #191f28; }
QSlider::groove:horizontal { background: #e5e8ec; height: 4px; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #3182f6; border-radius: 2px; }
QSlider::handle:horizontal { background: white; border: 1px solid #d1d6db; width: 17px; height: 17px; margin: -7px 0; border-radius: 9px; }
QCheckBox { spacing: 10px; min-height: 24px; }
QCheckBox::indicator { width: 36px; height: 22px; }
QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
QScrollBar::handle:vertical { background: #c8cdd4; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
'''


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
    painter.setPen(QPen(QColor('#3182f6'), 1.6))
    if name == '설정':
        painter.drawEllipse(5, 5, 14, 14); painter.drawEllipse(9, 9, 6, 6)
        for x1, y1, x2, y2 in [(12, 2, 12, 5), (12, 19, 12, 22), (2, 12, 5, 12), (19, 12, 22, 12), (5, 5, 7, 7), (17, 17, 19, 19), (5, 19, 7, 17), (17, 7, 19, 5)]: painter.drawLine(x1, y1, x2, y2)
    elif name == '실행':
        painter.drawArc(4, 4, 16, 16, 45 * 16, 270 * 16); painter.drawLine(12, 2, 12, 12)
    elif name == '입력창 동작':
        painter.drawRoundedRect(2, 6, 20, 12, 2, 2)
        for y in (9, 12):
            for x in (6, 10, 14, 18): painter.drawPoint(x, y)
        painter.drawLine(8, 15, 16, 15)
    elif name in ('보이스 클론', 'TTS'):
        for x, height in [(4, 3), (8, 7), (12, 10), (16, 5), (20, 3)]: painter.drawLine(x, 12 - height, x, 12 + height)
    elif name == '사운드보드':
        for x in (3, 14):
            for y in (3, 14): painter.drawRoundedRect(x, y, 7, 7, 2, 2)
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
    navigated = Signal(int)
    completed = Signal()
    compositionChanged = Signal()
    def __init__(self):
        super().__init__(); self.preedit = False; self.has_completions = False
    def event(self, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Tab and not self.preedit and self.has_completions:
            self.completed.emit(); return True
        return super().event(event)
    def inputMethodEvent(self, event):
        self.preedit = bool(event.preeditString()); super().inputMethodEvent(event); self.compositionChanged.emit()
    def keyPressEvent(self, event):
        if not self.preedit and self.has_completions and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.navigated.emit(-1 if event.key() == Qt.Key.Key_Up else 1); return
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


class StatusMessage(QWidget):
    """Status pill above the footer, with matching page scroll insets."""
    changed = Signal()
    def __init__(self, parent):
        super().__init__(parent)
        self._text = ''
        self.setObjectName('statusPill'); self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet('QWidget#statusPill { background: #ffffff; border: 1px solid #e5e8ed; border-radius: 18px; } QLabel { background: transparent; font-size: 12px; } QPushButton { background: transparent; border: none; padding: 2px 8px; }')
        layout = row(); layout.setContentsMargins(14, 0, 8, 0); layout.setSpacing(8); self.setLayout(layout)
        self.setFixedHeight(36)
        self.message = label('', muted=True); self.message.setWordWrap(False); self.message.setMinimumWidth(0); layout.addWidget(self.message, 1)
        self.dismiss = button('닫기', self.clear); self.dismiss.setFixedHeight(24); layout.addWidget(self.dismiss)
        shadow = QGraphicsDropShadowEffect(self); shadow.setBlurRadius(14); shadow.setOffset(0, 2); shadow.setColor(QColor(31, 49, 75, 30)); self.setGraphicsEffect(shadow)
        parent.installEventFilter(self); self.hide()

    def setText(self, text):
        self._text = text; self.message.setToolTip(text)
        self.setVisible(bool(text)); self.parentWidget().setVisible(bool(text)); self.fit_content(); self.changed.emit()

    def fit_content(self):
        if not self._text: return
        controls = sum(self.layout().itemAt(i).widget().sizeHint().width() + 8 for i in range(1, self.layout().count()) if not self.layout().itemAt(i).widget().isHidden())
        width = self.message.fontMetrics().horizontalAdvance(self._text.replace('\n', ' · ')) + controls + 24
        self.setFixedWidth(min(max(200, width), max(200, self.window().width() - 48)))
        self.layout().activate(); self.render_text()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize: self.fit_content()
        return False

    def render_text(self):
        self.message.setText(self.message.fontMetrics().elidedText(self._text.replace('\n', ' · '), Qt.TextElideMode.ElideRight, max(0, self.message.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event); self.render_text()

    def text(self):
        return self._text

    def clear(self):
        self.setText('')


class CheckBox(QCheckBox):
    """Keep checked/unchecked states legible regardless of Windows theme rendering."""
    def hitButton(self, point):
        return self.rect().contains(point)

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled(): painter.setOpacity(.45)
        painter.setPen(QColor('#333d4b'))
        painter.drawText(self.rect().adjusted(0, 0, -48, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())
        x, y = self.width() - 36, (self.height() - 22) // 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#3182f6' if self.isChecked() else '#d1d6db'))
        painter.drawRoundedRect(x, y, 36, 22, 11, 11)
        painter.setBrush(QColor('white'))
        painter.drawEllipse(x + (17 if self.isChecked() else 3), y + 3, 16, 16)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush); painter.setPen(QPen(QColor('#3182f6'), 1))
            painter.drawRoundedRect(x - 2, y - 2, 40, 26, 13, 13)


class ColorWell(QPushButton):
    def __init__(self, callback):
        super().__init__()
        self.color = QColor('white')
        self.setFixedSize(44, 22)
        self.clicked.connect(lambda: callback())

    def set_color(self, color):
        self.color = QColor(color); self.update()

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#007aff' if self.hasFocus() else '#c6c6c6'), 1))
        painter.setBrush(self.color)
        painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 9, 9)


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide(); item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout()); item.layout().deleteLater()


def card(layout):
    panel = QFrame(); panel.setObjectName('card'); body = column(panel, 20, 16); layout.addWidget(panel)
    return body
