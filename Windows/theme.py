"""Colours and stylesheet that mirror the macOS app; layout numbers come from Shared/app.json."""
import tempfile
from pathlib import Path

from config import CONTRACT

TOKENS = CONTRACT['theme']
ACCENT = TOKENS['accent']

# Sampled from the macOS window (system materials) so both platforms render the same page.
LIGHT = {
    'background': '#f9f9f9', 'card': '#ffffff', 'card_border': '#ebebeb', 'hairline': '#e6e6e6',
    'text': '#222222', 'secondary': '#808080', 'tertiary': '#b8b8b8',
    'fill': '#ebebeb', 'fill_hover': '#e3e3e3', 'fill_pressed': '#d9d9d9',
    'field': '#ffffff', 'field_border': '#d4d4d4', 'switch_off': '#e3e3e3', 'knob': '#ffffff', 'knob_border': 'rgba(0, 0, 0, 38)',
    'slider_track': '#e3e3e3', 'bar': 'rgba(255, 255, 255, 225)', 'bar_border': '#e3e3e3', 'selected': 'rgba(0, 0, 0, 20)',
    'backdrop': 'rgba(0, 0, 0, 46)', 'badge_off': '#a8a8a8', 'danger': '#ff3b30', 'success': '#28a745', 'warning': '#f08a00',
    'selection': '#cfe1fd', 'accent_soft': 'rgba(49, 130, 246, 31)', 'accent_faint': 'rgba(49, 130, 246, 15)',
    'preview': ('#a5c0fc', '#caaef5', '#fcc4b5'),
}
DARK = {
    'background': '#232323', 'card': '#1e1e1e', 'card_border': '#2f2f2f', 'hairline': '#343434',
    'text': '#e6e6e6', 'secondary': '#8c8c8c', 'tertiary': '#5c5c5c',
    'fill': '#333333', 'fill_hover': '#3b3b3b', 'fill_pressed': '#444444',
    'field': '#1e1e1e', 'field_border': '#404040', 'switch_off': '#3a3a3a', 'knob': '#f2f2f2', 'knob_border': 'rgba(0, 0, 0, 90)',
    'slider_track': '#3a3a3a', 'bar': 'rgba(44, 44, 44, 235)', 'bar_border': '#3a3a3a', 'selected': 'rgba(255, 255, 255, 26)',
    'backdrop': 'rgba(0, 0, 0, 110)', 'badge_off': '#5f5f5f', 'danger': '#ff453a', 'success': '#30d158', 'warning': '#ff9f0a',
    'selection': '#2a4a78', 'accent_soft': 'rgba(49, 130, 246, 51)', 'accent_faint': 'rgba(49, 130, 246, 26)',
    'preview': ('#405a97', '#644890', '#975f50'),
}

P = dict(LIGHT)
_hooks = []


def dark_system():
    import os
    forced = os.environ.get('STTS_APPEARANCE')
    if forced: return forced == 'dark'
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except (AttributeError, RuntimeError):
        return False


def use(dark):
    P.clear(); P.update(DARK if dark else LIGHT)
    for hook in list(_hooks): hook()


def on_change(hook):
    """Custom-painted icons register here so they follow a light/dark switch."""
    _hooks.append(hook); hook()


def _asset(name, svg):
    """Stylesheets load images only from files, so small vector assets are written once."""
    folder = Path(tempfile.gettempdir()) / 'STTS-ui'; folder.mkdir(exist_ok=True)
    path = folder / name
    if not path.is_file() or path.read_text(encoding='utf-8') != svg: path.write_text(svg, encoding='utf-8')
    return path.as_posix()


def _updown(color):
    # The macOS pop-up button indicator: a small up and down chevron pair.
    return _asset(f'updown-{color.strip("#")}.svg', f'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="14" viewBox="0 0 10 14">'
                  f'<path d="M2 5.2L5 2.2l3 3M2 8.8l3 3 3-3" fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def stylesheet():
    p, r = P, TOKENS
    card, control = r['card_radius'], r['control_radius']
    return f'''
QWidget {{ font-family: "Segoe UI Variable Text", "Segoe UI", "Malgun Gothic"; font-size: 13px; color: {p['text']}; }}
QWidget#main, QDialog#main, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {p['background']}; }}
QScrollArea {{ border: none; }}
QToolTip {{ background: {p['card']}; color: {p['text']}; border: 1px solid {p['card_border']}; border-radius: 6px; padding: 4px 8px; }}
QFrame#card {{ background: {p['card']}; border: 1px solid {p['card_border']}; border-radius: {card}px; }}
QFrame#dropZone {{ background: {p['card']}; border: 2px dashed {p['field_border']}; border-radius: {card}px; }}
QFrame#dropZone[active="true"] {{ background: {p['accent_faint']}; border: 2px dashed {ACCENT}; }}
QFrame#step {{ background: {p['fill']}; border: none; border-radius: 12px; }}
QFrame#hairline {{ background: {p['hairline']}; border: none; }}
QWidget#highlight {{ background: {p['accent_faint']}; }}
QLabel {{ background: transparent; }}
QLabel[heading="true"] {{ font-weight: 600; font-size: 14px; }}
QLabel[title="true"] {{ font-weight: 700; font-size: 20px; }}
QLabel[muted="true"] {{ color: {p['secondary']}; font-size: 12px; }}
QLabel[section="true"] {{ color: {p['secondary']}; font-size: 12px; font-weight: 600; padding-left: 6px; }}
QLabel[tone="danger"] {{ color: {p['danger']}; font-size: 12px; }}
QLabel[tone="secondary"] {{ color: {p['secondary']}; }}
QLabel[tone="tertiary"] {{ color: {p['tertiary']}; font-size: 12px; }}
QLabel[tone="accent"] {{ color: {ACCENT}; font-size: 12px; }}
QLabel[badge="ok"] {{ color: {p['success']}; background: rgba(40, 167, 69, 30); border-radius: 8px; padding: 1px 7px; font-size: 11px; font-weight: 600; }}
QLabel[badge="warn"] {{ color: {p['warning']}; background: rgba(240, 138, 0, 30); border-radius: 8px; padding: 1px 7px; font-size: 11px; font-weight: 600; }}

QPushButton {{ background: {p['fill']}; border: none; border-radius: {control}px; padding: 4px 11px; min-height: 18px; color: {p['text']}; }}
QPushButton:hover {{ background: {p['fill_hover']}; }}
QPushButton:pressed {{ background: {p['fill_pressed']}; }}
QPushButton:focus {{ border: 1px solid {ACCENT}; }}
QPushButton:disabled {{ color: {p['tertiary']}; }}
QPushButton#primary {{ background: {ACCENT}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: #478ff7; }}
QPushButton#primary:pressed {{ background: #2a72dc; }}
QPushButton#primary:disabled {{ background: {p['fill']}; color: {p['tertiary']}; }}
QPushButton#small {{ padding: 2px 8px; min-height: 16px; font-size: 11px; }}
QPushButton#record {{ background: {p['danger']}; color: white; font-weight: 600; }}
QPushButton#flat, QPushButton#link, QPushButton#icon, QPushButton#danger {{ background: transparent; border: none; padding: 2px 4px; }}
QPushButton#flat {{ color: {p['secondary']}; font-size: 12px; }}
QPushButton#flat:hover, QPushButton#icon:hover {{ color: {p['text']}; background: {p['fill']}; }}
QPushButton#link {{ color: {ACCENT}; text-align: left; font-size: 12px; }}
QPushButton#link:hover {{ text-decoration: underline; }}
QPushButton#icon, QPushButton#danger {{ min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; padding: 0; border-radius: 6px; }}
QPushButton#danger:hover {{ background: rgba(255, 59, 48, 26); }}
QPushButton:disabled#flat, QPushButton:disabled#link, QPushButton:disabled#icon, QPushButton:disabled#danger {{ background: transparent; }}
QPushButton#nav {{ text-align: left; background: transparent; border: none; border-radius: 0; padding: 0; }}
QPushButton#close {{ background: {p['fill']}; border: none; border-radius: 13px; padding: 0; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; }}
QPushButton#close:hover {{ background: {p['fill_hover']}; }}
QPushButton#play {{ background: {p['accent_soft']}; border: none; border-radius: 15px; padding: 0; min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; }}
QPushButton#playing {{ background: {ACCENT}; border: none; border-radius: 15px; padding: 0; min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; }}

QFrame#toolsOverlay {{ background: transparent; }}
QPushButton#toolBackdrop {{ background: {p['backdrop']}; border: none; border-radius: 0; }}
QFrame#toolDrawer {{ background: {p['background']}; border: 1px solid {p['card_border']}; border-bottom: none; border-top-left-radius: 24px; border-top-right-radius: 24px; }}
QFrame#grabber {{ background: {p['tertiary']}; border-radius: 2px; }}
QFrame#segments {{ background: {p['bar']}; border: 1px solid {p['bar_border']}; border-radius: 18px; }}
QPushButton#segment {{ background: transparent; padding: 0; min-height: 0; border: 1px solid transparent; border-radius: 14px; color: {p['secondary']}; font-weight: 600; font-size: 12px; }}
QPushButton#segment:checked {{ background: {p['selected']}; color: {p['text']}; }}
QPushButton#segment:focus {{ border: 1px solid transparent; }}
QPushButton#segment:checked:focus {{ border: 1px solid transparent; }}
QWidget#statusPill {{ background: {p['bar']}; border: 1px solid {p['bar_border']}; border-radius: 17px; }}
QWidget#statusPill QPushButton {{ background: transparent; border: none; padding: 2px 8px; color: {ACCENT}; font-size: 12px; }}
QFrame#preview {{ border-radius: 12px; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {p['preview'][0]}, stop:0.5 {p['preview'][1]}, stop:1 {p['preview'][2]}); }}

QLineEdit, QPlainTextEdit {{ background: {p['field']}; border: 1px solid {p['field_border']}; border-radius: {control}px; padding: 4px 7px; selection-background-color: {p['selection']}; selection-color: {p['text']}; }}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 2px solid rgba(49, 130, 246, 150); padding: 3px 6px; }}
QLineEdit:disabled, QPlainTextEdit:disabled {{ color: {p['tertiary']}; }}

QComboBox {{ background: {p['fill']}; border: none; border-radius: {control}px; padding: 3px 26px 3px 9px; min-height: 18px; }}
QComboBox:hover {{ background: {p['fill_hover']}; }}
QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox:disabled {{ color: {p['tertiary']}; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url("{_updown(p['text'])}"); width: 10px; height: 14px; }}
QComboBox::down-arrow:disabled {{ image: url("{_updown(p['tertiary'])}"); }}
QComboBox QAbstractItemView {{ background: {p['card']}; color: {p['text']}; border: 1px solid {p['card_border']}; border-radius: 8px; padding: 4px; outline: none; selection-background-color: {ACCENT}; selection-color: white; }}
QComboBox QAbstractItemView::item {{ min-height: 24px; padding: 0 8px; border-radius: 5px; }}

QSlider {{ min-height: 22px; }}
QSlider::groove:horizontal {{ background: {p['slider_track']}; height: 4px; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::sub-page:horizontal:disabled {{ background: {p['tertiary']}; }}
QSlider::handle:horizontal {{ background: {p['knob']}; border: 1px solid {p['knob_border']}; width: 20px; height: 14px; margin: -6px 0; border-radius: 7px; }}
QCheckBox {{ spacing: 10px; min-height: 24px; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['tertiary']}; border-radius: 3px; min-height: 28px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QMenu {{ background: {p['card']}; border: 1px solid {p['card_border']}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 5px 20px; border-radius: 5px; }}
QMenu::item:selected {{ background: {ACCENT}; color: white; }}
'''
