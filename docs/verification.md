# 검증 범위

## Windows

환경: Windows 11 x64, NVIDIA RTX 4080.

- Supertonic CPU·DirectML 음성 생성.
- Qwen 0.6B·1.7B 일반 목소리·클론의 CUDA 음성 생성. 생성 결과의 한국어 문장 인식.
- Whisper small·turbo·large의 CPU·CUDA 한국어 인식.
- 빈 데이터 폴더에서 EXE의 모델 다운로드 → 생성 → 가상 케이블 수신 → 프로그램 오디오 캡처 → 음성 인식.
- UI 렌더링, 케이블 상태·음량 진단, 업데이트 파일 해시 검증.
- Windows·TTS 단축어 회귀 테스트 33개.
- 0.1.1 가상 마이크 이름 변경·원래 이름 복구·반복 적용, 변경 후 실제 케이블 신호 수신.
- 0.1.3 처음 설정의 세 단계 안내, 설치용 `--show` 실행 시 백그라운드 설정과 관계없이 창 표시, 창 닫기 후 트레이 유지·다시 열기·종료 동작.

VB-CABLE이 이미 설치된 환경에서 검사했습니다. 드라이버가 없는 새 Windows의 최초 설치·재부팅, 실제 Discord 통화 상대의 수신, AMD·Intel GPU는 이 로컬 검증 범위에 포함되지 않습니다.

## macOS

[GitHub macOS 빌드](https://github.com/NONO6202/STTS/actions/runs/34156867771): macOS 26, Apple Silicon.

- 앱·DMG 생성, 번들 코드 서명 검사, 외부 Homebrew 경로 의존성 검사.
- Swift 테스트 15개와 Python 워커 프로토콜 테스트 10개 통과.

화면 클릭·가상 마이크 장치 생성 검사 2개는 GitHub 환경에서 제외했습니다. 실제 Mac의 첫 실행·권한 승인·Discord 통화와 모델 추론은 이 CI 검증 범위에 포함되지 않습니다. Apple 공증과 자동 업데이트용 서명 파일은 별도로 준비해야 합니다.

## Windows 10 호환성

0.1.1부터 Windows 10 22H2(빌드 19045) 이상의 설치를 허용합니다. 포함된 CUDA 12.8의 지원 범위에 맞춘 기준입니다. Windows 업데이트와 GPU 드라이버 업데이트를 적용해야 합니다.

- [Qt 6.10 지원 플랫폼](https://doc.qt.io/qt-6.10/supported-platforms.html): Windows 10 1809 이상.
- [CUDA 12.8 지원 플랫폼](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-installation-guide-microsoft-windows/index.html): Windows 10 22H2 포함.
- [OBS 앱별 오디오 캡처](https://obsproject.com/kb/application-audio-capture-guide): Windows 10 2004 이상에서 같은 프로세스 루프백 API 사용.

Windows 10 실기에서 설치·음성 송수신 검사는 아직 수행하지 않았습니다. 위 Windows 실기 검사 환경은 Windows 11입니다.
