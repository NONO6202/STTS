"""Settings navigation and editors; speech and persistence are owned by App."""
import json
import os
from pathlib import Path
import sys
from typing import TYPE_CHECKING

from localization import tr, message as localize_message, LANGUAGE, NATIVE_NAMES, SUPPORTED, system_languages, ui_language

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox
from config import CONTRACT, VERSION
from widgets import label, column, row, button, styled, section, clear_layout, icon_button, icon_for
from theme import ACCENT, on_change

if TYPE_CHECKING:
    from app import App


class SettingsPanel:
    """All settings live on one page of titled sections."""
    def __init__(self, app: 'App'):
        self.app = app

    def title(self, key):
        return tr(next(page['title'] for page in CONTRACT['settings'] if page['id'] == key))

    def show_menu(self):
        app = self.app
        clear_layout(app.settings_layout); layout = app.settings_layout
        from config import DEMO
        if DEMO: app.demo_notice(section(layout, tr('데모 버전')), '보이스 클론, TTS 단축어, 사운드보드, 마이크 효과, 실시간 자막은 정식판에서 사용할 수 있습니다.')
        self.runtime(section(layout, self.title('runtime')))
        self.microphone(section(layout, tr('가상 마이크')))
        self.input(section(layout, self.title('input')))
        self.models(section(layout, self.title('models')))
        line = row(); line.setContentsMargins(6, 0, 0, 0); line.addWidget(label(f'STTS {VERSION}', tone='tertiary')); line.addStretch()
        line.addWidget(styled(button(tr('처음 설정'), app.show_setup), 'link'))
        layout.addLayout(line)

    # Kept as entry points: each redraws the page with fresh model and login state.
    show_runtime = show_input = show_models = show_menu

    def runtime(self, layout):
        app = self.app
        from winutil import set_login
        app.check(layout, tr('로그인 시 자동 실행'), 'login', set_login)
        app.check(layout, tr('시작 시 백그라운드 실행'), 'background'); app.option(layout, tr('창 닫을 때'), 'close', CONTRACT['close_actions'])
        self.language(layout)

    def language(self, layout):
        app = self.app
        line = row(); caption = label(tr('앱 언어')); caption.setWordWrap(False); line.addWidget(caption, 1)
        box = QComboBox(); box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        box.addItem(tr('시스템 언어'), None)
        for code in SUPPORTED: box.addItem(NATIVE_NAMES[code], code)
        box.setCurrentIndex(max(0, box.findData(app.config.get('ui_language')))); line.addWidget(box); layout.addLayout(line)
        notice = row(); notice.setSpacing(6); hint = label(tr('다시 시작하면 언어가 바뀝니다.'), tone='secondary'); notice.addWidget(hint, 1)
        restart = styled(button(tr('다시 시작'), app.restart), 'small'); notice.addWidget(restart); holder = layout.addLayout(notice)
        def pending():
            # The UI text is fixed at launch, so a different choice waits for a restart.
            code = app.config.get('ui_language')
            changed = ui_language([code] if code else system_languages()) != LANGUAGE
            holder.setVisible(changed)
        def update(index):
            code = box.itemData(index)
            if code: app.config['ui_language'] = code
            else: app.config.pop('ui_language', None)
            app.save(); pending()
        box.currentIndexChanged.connect(update); pending()

    def microphone(self, layout):
        app = self.app
        ready = app.config['tts_enabled']
        line = row(); line.setSpacing(6); line.addWidget(label(tr('STTS 연결됨' if ready else 'TTS를 켜면 가상 마이크를 연결합니다.'), tone=None if ready else 'secondary'), 1)
        line.addWidget(styled(button(tr('연결 확인'), app.check_microphone), 'small')); line.addWidget(styled(button(tr('소리 설정'), lambda: os.startfile('ms-settings:sound')), 'small'))
        layout.addLayout(line)

    def input(self, layout):
        app = self.app
        app.check(layout, tr('작성 중인 내용 유지'), 'keep_draft')
        app.check(layout, tr('입력창 밖을 클릭하면 닫기'), 'outside')
        app.check(layout, tr('마우스를 흔들면 닫기'), 'shake', lambda enabled: app.boxes['shake_sensitivity'].setEnabled(enabled))
        app.option(layout, tr('흔들기 민감도'), 'shake_sensitivity', list(CONTRACT['shake_sensitivities'])); app.boxes['shake_sensitivity'].setEnabled(app.config['shake'])

    def models(self, layout):
        app = self.app
        layout.accessory(app.accessory(tr('새로고침'), 'arrow.clockwise', self.show_menu))
        catalog = json.loads((Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'models.json').read_text(encoding='utf-8'))
        current = {f"{key}-{asset.get('variant', asset['revision'][:12])}": asset for key, asset in catalog.items()}
        paths = sorted(p for p in app.model_root.iterdir() if p.is_dir())
        if not paths: layout.addWidget(label(tr('다운로드한 모델이 없습니다.'), muted=True))
        names = CONTRACT['model_names']
        for path in paths:
            size = sum(f.stat().st_size for f in path.rglob('*') if f.is_file()); line = row(); details = column(spacing=2)
            asset = current.get(path.name)
            state = tr('사용 가능' if asset else '이전 버전 · 현재 사용하지 않음')
            details.addWidget(label(localize_message(names.get(path.name.split('-')[0], path.name.split('-')[0])))); details.addWidget(label(f'{size / 1024**3:.2f} GB · {state}', muted=True)); line.addLayout(details, 1)
            control = icon_button('trash', tr('삭제'), lambda p=path: app.delete_model(p), destructive=True); control.setEnabled(not (app.tts_busy or app.voice_busy or app.capture)); line.addWidget(control); layout.addLayout(line)
        folder = styled(button(app.model_root.as_posix() if hasattr(app.model_root, 'as_posix') else str(app.model_root), lambda: os.startfile(app.model_root)), 'link')
        folder.setToolTip(tr('폴더 열기')); on_change(lambda: folder.setIcon(icon_for('folder', ACCENT, 16)))
        layout.addWidget(folder)
