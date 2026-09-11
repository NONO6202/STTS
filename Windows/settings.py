"""Settings navigation and editors; speech and persistence are owned by App."""
import json
import os
from pathlib import Path
import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QLabel, QHBoxLayout
from config import CONTRACT, VERSION
from widgets import label, column, row, button, divider, icon_for, clear_layout

if TYPE_CHECKING:
    from app import App


class SettingsPanel:
    def __init__(self, app: 'App'):
        self.app = app

    def clear(self, title=None):
        app = self.app
        clear_layout(app.settings_layout)
        if title:
            header = row(); header.addWidget(button('‹ 설정', self.show_menu)); header.addWidget(label(title, heading=True)); header.addStretch()
            app.settings_layout.addLayout(header); app.settings_layout.addWidget(divider()); app.settings_layout.addSpacing(4)
        return app.settings_layout


    def show_menu(self):
        app = self.app
        layout = self.clear(); title = label('설정', heading=True); title.setStyleSheet('font-size: 24px; font-weight: 700;'); layout.addWidget(title)
        pages = {'runtime': self.show_runtime, 'input': self.show_input, 'models': self.show_models}
        for page in CONTRACT['settings']:
            name, callback = page['title'], pages[page['id']]
            control = QPushButton(); control.setObjectName('nav'); control.setFixedHeight(68)
            content = QHBoxLayout(control); content.setContentsMargins(20, 0, 20, 0); content.setSpacing(14)
            image = QLabel(); image.setPixmap(icon_for(name).pixmap(24, 24)); image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            text = label(name, heading=True); text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            arrow = label('›', muted=True); arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            content.addWidget(image); content.addWidget(text); content.addStretch(); content.addWidget(arrow)
            control.clicked.connect(lambda checked=False, fn=callback: fn()); layout.addWidget(control)
        line = row(); line.addWidget(label(f'STTS {VERSION}', muted=True)); line.addStretch()
        line.addWidget(button('처음 설정', app.show_setup))
        layout.addLayout(line)


    def show_runtime(self):
        app = self.app
        from winutil import set_login
        layout = self.clear('실행'); app.check(layout, '로그인 시 자동 실행', 'login', set_login)
        app.check(layout, '시작 시 백그라운드 실행', 'background'); app.option(layout, '창 닫을 때', 'close', CONTRACT['close_actions'])
        layout.addWidget(divider()); layout.addWidget(label('가상 마이크', heading=True))
        line = row(); line.addWidget(button('연결 확인', app.check_microphone)); line.addWidget(button('소리 설정', lambda: os.startfile('ms-settings:sound'))); line.addStretch(); layout.addLayout(line)


    def show_input(self):
        app = self.app
        layout = self.clear('입력창 동작'); layout.addWidget(label('입력창 닫기', heading=True))
        app.check(layout, '입력창 밖을 클릭하면 닫기', 'outside')
        app.check(layout, '마우스를 흔들면 닫기', 'shake', lambda enabled: app.boxes['shake_sensitivity'].setEnabled(enabled))
        app.option(layout, '흔들기 민감도', 'shake_sensitivity', list(CONTRACT['shake_sensitivities'])); app.boxes['shake_sensitivity'].setEnabled(app.config['shake'])


    def show_models(self):
        app = self.app
        layout = self.clear('모델 관리'); header = row(); header.addWidget(label('다운로드한 모델', heading=True), 1)
        header.addWidget(button('폴더 열기', lambda: os.startfile(app.model_root))); header.addWidget(button('새로고침', self.show_models)); layout.addLayout(header)
        catalog = json.loads((Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'models.json').read_text(encoding='utf-8'))
        current = {f"{key}-{asset.get('variant', asset['revision'][:12])}": asset for key, asset in catalog.items()}
        layout.addWidget(label(str(app.model_root), muted=True)); paths = sorted(p for p in app.model_root.iterdir() if p.is_dir())
        if not paths: layout.addWidget(label('다운로드한 모델이 없습니다.', muted=True))
        names = CONTRACT['model_names']
        for path in paths:
            size = sum(f.stat().st_size for f in path.rglob('*') if f.is_file()); line = row(); details = column(spacing=4)
            asset = current.get(path.name)
            state = '사용 가능' if asset else '이전 버전 · 현재 사용하지 않음'
            details.addWidget(label(names.get(path.name.split('-')[0], path.name.split('-')[0]))); details.addWidget(label(f'{size / 1024**3:.2f} GB · {state}', muted=True)); line.addLayout(details, 1)
            control = button('삭제', lambda p=path: app.delete_model(p)); control.setEnabled(not (app.tts_busy or app.voice_busy or app.capture)); line.addWidget(control); layout.addLayout(line)
