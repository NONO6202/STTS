# 0.1.0 검증

## Windows

환경: Windows 11 x64, NVIDIA RTX 4080.

- Supertonic CPU·DirectML 음성 생성.
- Qwen 0.6B·1.7B 일반 목소리·클론의 CUDA 음성 생성. 생성 결과의 한국어 문장 인식.
- Whisper small·turbo·large의 CPU·CUDA 한국어 인식.
- 빈 데이터 폴더에서 EXE의 모델 다운로드 → 생성 → 가상 케이블 수신 → 프로그램 오디오 캡처 → 음성 인식.
- UI 렌더링, 케이블 상태·음량 진단, 업데이트 파일 해시 검증.
- Windows 회귀 테스트 28개.

VB-CABLE이 이미 설치된 환경에서 검사했습니다. 드라이버가 없는 새 Windows의 최초 설치·재부팅, 실제 Discord 통화 상대의 수신, AMD·Intel GPU는 이 로컬 검증 범위에 포함되지 않습니다.

## macOS

[GitHub macOS 빌드](https://github.com/NONO6202/STTS/actions/runs/34156867771): macOS 26, Apple Silicon.

- 앱·DMG 생성, 번들 코드 서명 검사, 외부 Homebrew 경로 의존성 검사.
- Swift 테스트 15개와 Python 워커 프로토콜 테스트 10개 통과.

화면 클릭·가상 마이크 장치 생성 검사 2개는 GitHub 환경에서 제외했습니다. 실제 Mac의 첫 실행·권한 승인·Discord 통화와 모델 추론은 이 CI 검증 범위에 포함되지 않습니다. Apple 공증과 자동 업데이트용 서명 파일은 별도로 준비해야 합니다.
