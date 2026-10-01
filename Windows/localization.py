"""Shared UI translations; stored option identifiers and user text are unchanged."""
import ctypes
import json
import os
from pathlib import Path
import re
import sys

SUPPORTED = ('ko', 'en', 'ja', 'zh-Hans', 'es', 'fr', 'de', 'pt')
NATIVE_NAMES = {'ko': '한국어', 'en': 'English', 'ja': '日本語', 'zh-Hans': '简体中文', 'es': 'Español', 'fr': 'Français', 'de': 'Deutsch', 'pt': 'Português'}
RESOURCE_ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
CATALOG = json.loads((RESOURCE_ROOT / 'Shared/localization.json').read_text(encoding='utf-8'))


def system_languages():
    override = os.environ.get('STTS_UI_LANGUAGE')
    if override: return [override]
    if sys.platform == 'win32':
        from ctypes import wintypes
        count, size = wintypes.ULONG(), wintypes.ULONG()
        get = ctypes.windll.kernel32.GetUserPreferredUILanguages
        if get(8, ctypes.byref(count), None, ctypes.byref(size)) and size.value:
            buffer = ctypes.create_unicode_buffer(size.value)
            if get(8, ctypes.byref(count), buffer, ctypes.byref(size)):
                return [code for code in buffer[:size.value].split('\0') if code]
    return ['en']


def chosen_language():
    """The app language picked in settings, or None to follow the system."""
    try:
        from config import data_directory
        value = json.loads((data_directory() / 'settings.json').read_text(encoding='utf-8')).get('ui_language')
    except (OSError, ValueError, AttributeError): return None
    return value if value in SUPPORTED else None


def ui_language(preferred):
    for code in preferred:
        base = code.replace('_', '-').lower().split('-')[0]
        if base == 'zh': return 'zh-Hans'
        if base in SUPPORTED: return base
    return 'en'


def app_languages():
    chosen = None if os.environ.get('STTS_UI_LANGUAGE') else chosen_language()
    return [chosen] if chosen else system_languages()


LANGUAGE = ui_language(app_languages())


def tr(key, *arguments):
    result = key if LANGUAGE == 'ko' else CATALOG['strings'][LANGUAGE].get(key, CATALOG['strings']['en'].get(key, key))
    for index, value in enumerate(arguments): result = result.replace('{'+str(index)+'}', str(value))
    return result


def language_name(code):
    return CATALOG['languageNames'][LANGUAGE].get(code, CATALOG['languageNames']['en'].get(code, code))


def speech_language(preferred, supported):
    for requested in list(preferred) + ['en']:
        code = requested.replace('_', '-').lower()
        exact = next((item for item in supported if item.lower() == code), None)
        if exact: return exact
        parts = code.split('-'); base = parts[0]
        if base == 'zh':
            traditional = any(part in parts for part in ('hant', 'tw', 'hk', 'mo'))
            candidates = ('zh-tw', 'zh-hant', 'zh-hk') if traditional else ('zh-cn', 'zh-hans')
            for candidate in candidates:
                match = next((item for item in supported if item.lower() == candidate), None)
                if match: return match
        generic = next((item for item in supported if item.lower() == base), None)
        if generic: return generic
        match = next((item for item in sorted(supported) if item.lower().split('-')[0] == base), None)
        if match: return match
    return next(iter(supported), 'en')


_templates = []
for _key in sorted(CATALOG['strings']['en'], key=len, reverse=True):
    if '{0}' in _key:
        _pattern = re.escape(_key)
        for _index in range(10): _pattern = _pattern.replace(re.escape('{'+str(_index)+'}'), '(.*?)')
        _templates.append((_key, re.compile('^'+_pattern+'$', re.S)))


def message(source):
    if LANGUAGE == 'ko' or source in CATALOG['strings']['en']: return tr(source)
    for key, pattern in _templates:
        match = pattern.fullmatch(source)
        if match: return tr(key, *match.groups())
    return source


def install_qt_translations(application):
    from PySide6.QtCore import QLibraryInfo, QTranslator
    code = {'zh-Hans': 'zh_CN', 'pt': 'pt_BR'}.get(LANGUAGE, LANGUAGE)
    translator = QTranslator(application)
    if translator.load('qtbase_' + code, QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        application.installTranslator(translator)
    application._stts_translator = translator
