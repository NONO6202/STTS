# Steam 배포

Windows와 macOS 디포를 하나의 Steam 빌드로 올립니다. 비밀번호와 Steam Guard 코드는 SteamCMD에 직접 입력하며 저장하지 않습니다.

## Steamworks 설정

| 항목 | 값 |
| --- | --- |
| 디포 | Windows 디포(운영체제: Windows, 64비트), macOS 디포(운영체제: macOS) |
| 실행 옵션 | Windows `STTS.exe`, macOS `STTS.app` |
| 브랜치 | 업로드는 `beta`, 확인 후 Steamworks에서 `default`로 반영 |

Windows 가상 마이크(VB-CABLE)는 Steam 설치 스크립트를 쓰지 않습니다. 첫 실행 때 STTS가 드라이버가 없음을 확인하고 **가상 마이크 연결 점검** 창을 엽니다. **가상 마이크 설치**를 누르면 관리자 승인 한 번으로 드라이버 설치와 마이크 이름 변경을 마치고, 사용자의 기본 소리 장치를 되돌립니다. 설치 후 PC를 재시작합니다.

## 빌드

Windows:

```powershell
powershell -File Windows/build.ps1 -Steam
```

`Windows/build/steam`에 디포 내용이 생성됩니다. 업로드할 Mac의 같은 경로로 복사합니다.

macOS:

```sh
bash Support/build-macos.sh
```

## 업로드

```sh
brew install --cask steamcmd
STEAM_APP_ID=앱ID STEAM_DEPOT_WINDOWS=윈도우디포ID STEAM_DEPOT_MAC=맥디포ID STEAM_USER=스팀계정 bash Support/steam-upload.sh
```

`STEAM_PREVIEW=1`을 붙이면 파일 구성만 확인하고 업로드하지 않습니다.

## 출시 전 확인

- Steam 라이브러리에서 베타 브랜치로 설치해 첫 실행, 가상 마이크 설치, Discord 입력, STT 자막을 확인합니다.
- 콘텐츠 설문에서 실시간 생성 AI 콘텐츠(TTS·보이스 클론)를 공개합니다.
- 기본 TTS인 gTTS가 입력 문장을 Google에 전송한다는 점을 스토어 설명에 적습니다.
- 유료 판매 시 VB-CABLE 번들 조건을 VB-Audio에 확인합니다.
- Steam으로 제거해도 VB-CABLE 드라이버와 `%LOCALAPPDATA%\STTS`의 사용자 데이터는 남습니다.
