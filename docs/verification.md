# Windows 검증

환경: Windows 11 x64, NVIDIA RTX 4080.

- Supertonic CPU·DirectML 음성 생성.
- Qwen 0.6B·1.7B 일반 목소리·클론의 CUDA 음성 생성. 생성 결과의 한국어 문장 인식.
- Whisper small·turbo·large의 CPU·CUDA 한국어 인식.
- 빈 데이터 폴더에서 EXE의 모델 다운로드 → 생성 → 가상 케이블 수신 → 프로그램 오디오 캡처 → 음성 인식.
- UI 렌더링, 케이블 상태·음량 진단, 업데이트 파일 해시 검증.
- Windows 회귀 테스트 28개.

VB-CABLE이 이미 설치된 환경에서 검사했습니다. 드라이버가 없는 새 Windows의 최초 설치·재부팅, 실제 Discord 통화 상대의 수신, AMD·Intel GPU는 이 로컬 검증 범위에 포함되지 않습니다.
