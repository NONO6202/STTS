"""Reusable Qt controls, input windows, and keyboard event handling."""
from localization import tr, message as localize_message

from PySide6.QtCore import Qt, QObject, Signal, Slot, QEvent, QRectF, QPointF
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QKeySequence
from PySide6.QtWidgets import QCheckBox, QWidget, QFrame, QLabel, QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout, QSizePolicy, QGraphicsDropShadowEffect


from theme import P, ACCENT, TOKENS


def label(text='', heading=False, muted=False, section=False, tone=None, title=False):
    result = QLabel(text); result.setWordWrap(True)
    result.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    result.setProperty('heading', heading); result.setProperty('muted', muted); result.setProperty('section', section); result.setProperty('title', title)
    if tone: result.setProperty('tone', tone)
    return result


def restyle(widget, **properties):
    for key, value in properties.items(): widget.setProperty(key, value)
    widget.style().unpolish(widget); widget.style().polish(widget)


def column(parent=None, margins=0, spacing=12):
    layout = QVBoxLayout(parent); layout.setContentsMargins(margins, margins, margins, margins); layout.setSpacing(spacing)
    return layout


def row():
    layout = QHBoxLayout(); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(8)
    return layout


def button(text, callback):
    result = QPushButton(text); result.clicked.connect(lambda: callback()); return result


def divider():
    result = QFrame(); result.setObjectName('hairline'); result.setFixedHeight(1); return result


def styled(control, name):
    control.setObjectName(name); return control


# Page and tool names map to the same SF Symbols the macOS app shows.
SYMBOLS = {'TTS': 'waveform', '마이크': 'mic', 'STT': 'captions.bubble', '설정': 'gearshape',
           **{item['title']: item['symbol'] for item in __import__('config').CONTRACT['tools']}}


def icon_for(name, color=None, size=24):
    """Line icons drawn on a 24-point grid at 3x so they stay crisp at any Windows scale."""
    name = SYMBOLS.get(name, name); color = QColor(color or ACCENT)
    ratio = 3; image = QPixmap(size * ratio, size * ratio); image.setDevicePixelRatio(ratio); image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image); painter.setRenderHint(QPainter.RenderHint.Antialiasing); painter.scale(size / 24, size / 24)
    pen = QPen(color, 1.7); pen.setCapStyle(Qt.PenCapStyle.RoundCap); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin); painter.setPen(pen)
    fill = lambda: (painter.setBrush(color), painter.setPen(Qt.PenStyle.NoPen))
    def lines(*points):
        path = QPainterPath(QPointF(*points[0]))
        for point in points[1:]: path.lineTo(QPointF(*point))
        painter.drawPath(path)
    if name == 'waveform':
        for x, height in [(4, 2), (7.5, 5), (11, 8.5), (14.5, 6), (18, 3.5), (21, 1.5)]: painter.drawLine(QPointF(x, 12 - height), QPointF(x, 12 + height))
    elif name.startswith('mic'):
        painter.drawRoundedRect(QRectF(8.5, 2.5, 7, 12), 3.5, 3.5)
        painter.drawArc(QRectF(5, 6.5, 14, 12), 200 * 16, 140 * 16); painter.drawLine(QPointF(12, 18.5), QPointF(12, 21.5))
    elif name.startswith('captions.bubble') or name == 'text.bubble':
        painter.drawRoundedRect(QRectF(3, 4, 18, 13), 3.5, 3.5); lines((8, 17), (7, 21), (12, 17))
        painter.drawLine(QPointF(7.5, 9), QPointF(16.5, 9)); painter.drawLine(QPointF(7.5, 12.5), QPointF(13.5, 12.5))
    elif name == 'gearshape':
        painter.drawEllipse(QPointF(12, 12), 3, 3)
        path = QPainterPath()
        import math
        for index in range(16):
            angle = math.pi * 2 * index / 16; radius = 9 if index % 2 == 0 else 7
            point = QPointF(12 + radius * math.cos(angle), 12 + radius * math.sin(angle))
            path.moveTo(point) if index == 0 else path.lineTo(point)
        path.closeSubpath(); painter.drawPath(path)
    elif name == 'square.grid.2x2':
        for x in (3.5, 13.5):
            for y in (3.5, 13.5): painter.drawRoundedRect(QRectF(x, y, 7, 7), 2, 2)
    elif name in ('arrow.counterclockwise', 'arrow.clockwise'):
        if name == 'arrow.counterclockwise': painter.translate(24, 0); painter.scale(-1, 1)
        painter.drawArc(QRectF(5, 5, 14, 14), 110 * 16, 290 * 16); lines((5.5, 4), (6.8, 8.7), (11.5, 7.6))
    elif name == 'trash':
        painter.drawLine(QPointF(4, 6.5), QPointF(20, 6.5)); lines((9, 6.5), (9.5, 3.5), (14.5, 3.5), (15, 6.5))
        lines((6, 6.5), (7, 20.5), (17, 20.5), (18, 6.5)); painter.drawLine(QPointF(10.5, 10), QPointF(10.5, 17)); painter.drawLine(QPointF(13.5, 10), QPointF(13.5, 17))
    elif name == 'pencil':
        lines((5, 19), (5.5, 15.5), (15.5, 5.5), (18.5, 8.5), (8.5, 18.5), (5, 19)); painter.drawLine(QPointF(13.5, 7.5), QPointF(16.5, 10.5))
    elif name == 'folder':
        lines((3, 18.5), (3, 6), (9, 6), (11, 8.5), (21, 8.5), (21, 18.5), (3, 18.5))
    elif name in ('play.fill', 'stop.fill', 'record.circle'):
        if name == 'record.circle': painter.drawEllipse(QPointF(12, 12), 8.5, 8.5); fill(); painter.drawEllipse(QPointF(12, 12), 4.5, 4.5)
        elif name == 'play.fill': fill(); path = QPainterPath(QPointF(8, 5)); path.lineTo(19, 12); path.lineTo(8, 19); path.closeSubpath(); painter.drawPath(path)
        else: fill(); painter.drawRoundedRect(QRectF(6.5, 6.5, 11, 11), 2, 2)
    elif name == 'chevron.left': lines((14.5, 5), (8, 12), (14.5, 19))
    elif name == 'chevron.right': lines((9.5, 5), (16, 12), (9.5, 19))
    elif name == 'plus': painter.drawLine(QPointF(12, 5), QPointF(12, 19)); painter.drawLine(QPointF(5, 12), QPointF(19, 12))
    elif name == 'square.and.arrow.down':
        lines((12, 3), (12, 14)); lines((7.5, 9.5), (12, 14), (16.5, 9.5)); lines((4, 13), (4, 20), (20, 20), (20, 13))
    elif name == 'xmark':
        pen.setWidthF(2.2); painter.setPen(pen); painter.drawLine(QPointF(7, 7), QPointF(17, 17)); painter.drawLine(QPointF(17, 7), QPointF(7, 17))
    elif name == 'person.wave.2':
        painter.drawEllipse(QPointF(12, 8), 3.5, 3.5); painter.drawArc(QRectF(5.5, 13, 13, 12), 20 * 16, 140 * 16)
        painter.drawArc(QRectF(1, 3.5, 7, 9), 110 * 16, 140 * 16); painter.drawArc(QRectF(16, 3.5, 7, 9), -70 * 16, 140 * 16)
    else:
        painter.drawRoundedRect(QRectF(3, 4, 18, 13), 3.5, 3.5)
    painter.end(); return QIcon(image)


def icon_button(symbol, title, callback, destructive=False, tint=None):
    """Borderless 26-point icon button, like the macOS drawer rows."""
    control = styled(QPushButton(), 'danger' if destructive else 'icon'); control.clicked.connect(lambda: callback())
    control.setToolTip(title); control.setAccessibleName(title)
    control.setIconSize(__import__('PySide6.QtCore', fromlist=['QSize']).QSize(15, 15))
    from theme import on_change
    on_change(lambda: control.setIcon(icon_for(symbol, tint or (P['danger'] if destructive else P['secondary']))))
    return control


class Bridge(QObject):
    dispatch = Signal(object, object)
    def __init__(self, owner, parent):
        super().__init__(parent); self.owner = owner
        self.dispatch.connect(self.deliver, Qt.ConnectionType.QueuedConnection)
    @Slot(object, object)
    def deliver(self, callback, args):
        if self.owner.closing: return
        try: callback(*args)
        except Exception as error: self.owner.status.setText(localize_message(str(error)))


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
        painter.drawRoundedRect(self.rect(), 12, 12)


class ComposerEdit(QLineEdit):
    submitted = Signal()
    dismissed = Signal()
    navigated = Signal(int)
    recalled = Signal(int)
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
        if not self.preedit and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = -1 if event.key() == Qt.Key.Key_Up else 1
            (self.navigated if self.has_completions else self.recalled).emit(step); return
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
        if not code and event.key() == Qt.Key.Key_QuoteLeft: code = 0xC0
        if not code:
            code = int(event.key()) if int(event.key()) < 256 else 0
            if Qt.Key.Key_F1 <= event.key() <= Qt.Key.Key_F24: code = 0x70 + int(event.key()) - int(Qt.Key.Key_F1)
        if not code or (not bits & 0xB and not 0x70 <= code <= 0x87 and not (code == 0xC0 and bits == 0)):
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
        layout = row(); layout.setContentsMargins(14, 0, 8, 0); layout.setSpacing(8); self.setLayout(layout)
        self.setFixedHeight(36)
        self.message = label('', muted=True); self.message.setWordWrap(False); self.message.setMinimumWidth(0); layout.addWidget(self.message, 1)
        self.dismiss = button(tr('닫기'), self.clear); self.dismiss.setFixedHeight(24); layout.addWidget(self.dismiss)
        shadow = QGraphicsDropShadowEffect(self); shadow.setBlurRadius(14); shadow.setOffset(0, 2); shadow.setColor(QColor(31, 49, 75, 30)); self.setGraphicsEffect(shadow)
        parent.installEventFilter(self); self.hide()

    def setText(self, text):
        text = localize_message(text)
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
        self.setText(tr(''))


class CheckBox(QCheckBox):
    """A macOS-style switch drawn the same on every Windows theme, with an optional detail line."""
    def __init__(self, text='', detail='', large=False):
        super().__init__(text); self.detail = detail; self.large = large
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def hitButton(self, point):
        return self.rect().contains(point)

    def _detail_font(self):
        font = self.font(); font.setPixelSize(11); font.setBold(False); return font

    def sizeHint(self):
        # Two lines of text need the real font heights; Malgun Gothic is taller than the macOS system font.
        from PySide6.QtGui import QFontMetrics
        hint = super().sizeHint()
        lines = self.fontMetrics().height() + 2 + QFontMetrics(self._detail_font()).height() + 2 if self.detail else 24
        hint.setHeight(max(hint.height(), lines)); return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint(); hint.setHeight(self.sizeHint().height()); return hint

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled(): painter.setOpacity(.45)
        width, height = (54, 24) if self.large else (44, 20)
        text = self.rect().adjusted(0, 0, -(width + 12), 0)
        painter.setFont(self.font()); painter.setPen(QColor(P['text']))
        if self.detail:
            from PySide6.QtGui import QFontMetrics
            metrics, small = self.fontMetrics(), self._detail_font()
            top = (self.height() - metrics.height() - 2 - QFontMetrics(small).height()) // 2
            painter.drawText(text.adjusted(0, top, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, self.text())
            painter.setFont(small); painter.setPen(QColor(P['secondary']))
            painter.drawText(text.adjusted(0, top + metrics.height() + 2, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, self.detail)
        else:
            painter.drawText(text, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())
        track = QRectF(self.width() - width - 1, (self.height() - height) / 2, width, height)
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(ACCENT if self.isChecked() else P['switch_off']))
        painter.drawRoundedRect(track, height / 2, height / 2)
        # macOS 26 knobs are wider than tall.
        knob_height = height - 4; knob_width = knob_height * 1.45
        knob = QRectF(track.right() - 2 - knob_width if self.isChecked() else track.left() + 2, track.top() + 2, knob_width, knob_height)
        painter.setPen(QPen(QColor(0, 0, 0, 30), .8)); painter.setBrush(QColor(P['knob'])); painter.drawRoundedRect(knob, knob_height / 2, knob_height / 2)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush); painter.setPen(QPen(QColor(49, 130, 246, 150), 2.5))
            painter.drawRoundedRect(track.adjusted(-2, -2, 2, 2), height / 2 + 2, height / 2 + 2)


class ColorWell(QPushButton):
    def __init__(self, callback):
        super().__init__()
        self.color = QColor('white')
        self.setFixedSize(46, 24); self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.clicked.connect(lambda: callback())

    def set_color(self, color):
        self.color = QColor(color); self.update()

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Matches the macOS colour well: a capsule swatch with a thin outline.
        outer = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(ACCENT) if self.hasFocus() else QColor(128, 128, 128, 90), 1.5 if self.hasFocus() else 1))
        painter.setBrush(self.color); painter.drawRoundedRect(outer, outer.height() / 2, outer.height() / 2)


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide(); item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout()); item.layout().deleteLater()


def badge(name, active, size=32):
    """Rounded, filled feature icon shown beside a page's main switch."""
    ratio = 3; image = QPixmap(size * ratio, size * ratio); image.setDevicePixelRatio(ratio); image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image); painter.setRenderHint(QPainter.RenderHint.Antialiasing); painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(ACCENT if active else P['badge_off'])); painter.drawRoundedRect(QRectF(0, 0, size, size), size / 4, size / 4)
    inner = size * .56; offset = (size - inner) / 2
    painter.drawPixmap(QRectF(offset, offset, inner, inner), icon_for(name, 'white', 24).pixmap(72, 72), QRectF(0, 0, 72, 72)); painter.end()
    return image


class Section(QWidget):
    """A titled card whose rows are separated by inset hairlines.

    Mirrors the QLayout calls the page builders already use, so a Section can stand in for a layout.
    """
    def __init__(self, title=None):
        super().__init__()
        outer = column(self, 0, 8)
        self.header = row(); self.header.setContentsMargins(0, 0, 6, 0)
        if title: self.header.addWidget(label(title, section=True))
        self.header.addStretch()
        self.header_widget = QWidget(); self.header_widget.setLayout(self.header); self.header_widget.setMinimumHeight(20); self.header_widget.setVisible(bool(title))
        outer.addWidget(self.header_widget)
        self.card = QFrame(); self.card.setObjectName('card'); outer.addWidget(self.card)
        self.rows = column(self.card, 0, 0); self.rows.setContentsMargins(0, 0, 0, 0)

    def accessory(self, widget):
        self.header_widget.show(); self.header.addWidget(widget); return widget

    def addWidget(self, widget, stretch=0, alignment=None):
        inset = TOKENS['row_inset']
        holder = QWidget(); body = column(holder, 0, 0)
        if self.rows.count():
            rule = QHBoxLayout(); rule.setContentsMargins(inset, 0, 0, 0); rule.addWidget(divider()); body.addLayout(rule)
        line = QHBoxLayout(); line.setContentsMargins(inset, 8, inset, 8); line.setSpacing(0)
        if alignment is not None: line.addWidget(widget, 0, alignment)
        else: line.addWidget(widget)
        body.addLayout(line); holder.setMinimumHeight(TOKENS['row_height'])
        self.rows.addWidget(holder); return holder

    def addLayout(self, layout, stretch=0):
        widget = QWidget(); layout.setContentsMargins(0, 0, 0, 0); widget.setLayout(layout)
        return self.addWidget(widget)

    def addSpacing(self, size): pass


class DropZone(QFrame):
    """A dashed card that accepts files with the given suffixes dragged in from Explorer."""
    def __init__(self, suffixes, dropped):
        super().__init__(); self.setObjectName('dropZone'); self.setAcceptDrops(True)
        self.suffixes, self.dropped = suffixes, dropped

    def files(self, event):
        from pathlib import Path
        return [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in self.suffixes]

    def dragEnterEvent(self, event):
        if self.files(event): event.acceptProposedAction(); restyle(self, active=True)

    def dragMoveEvent(self, event):
        if self.files(event): event.acceptProposedAction()

    def dragLeaveEvent(self, event): restyle(self, active=False)

    def dropEvent(self, event):
        restyle(self, active=False); files = self.files(event)
        if files: event.acceptProposedAction(); self.dropped(files)


def section(layout, title=None):
    result = Section(title); layout.addWidget(result); return result

