# Steam 배포

Windows와 macOS 디포를 하나의 Steam 빌드로 올립니다. 비밀번호와 Steam Guard 코드는 SteamCMD에 직접 입력하며 저장하지 않습니다.

## Steamworks 설정

| 항목 | 값 |
| --- | --- |
| 디포 | Windows 디포(운영체제: Windows, 64비트), macOS 디포(운영체제: macOS) |
| 실행 옵션 | Windows `STTS.exe`, macOS `STTS.app` |
| 브랜치 | 업로드는 `beta`, 확인 후 Steamworks에서 `default`로 반영 |
| 데모 | 앱 5369140, 디포 5369141(Windows)·5369142(macOS), 실행 옵션은 정식판과 같음 |
| 도전과제 | `Shared/app.json`의 `achievements` 10개. 이름·설명·아이콘은 Steamworks에 등록 |

## 도전과제

진행도는 기기의 `achievements.json`에 저장합니다. 새로 달성하면 STTS가 `--steam-achievements` 보조 프로세스를 잠깐 실행해 Steam에 알리고 바로 종료합니다. 상시 실행되는 STTS가 Steam에 게임 실행 중으로 표시되지 않게 하기 위해서입니다. Steam이 꺼져 있으면 다음 실행 때 다시 알립니다.

빌드에는 Steamworks SDK의 재배포 라이브러리(`steam_api64.dll`, `libsteam_api.dylib`)가 필요합니다. SDK는 저장소에 넣지 않습니다. 기본 위치는 저장소 옆 `steamworks_sdk/sdk`(macOS)와 `Windows/vendor/steam_api64.dll`(Windows)이며, `STEAMWORKS_SDK` 환경 변수로 바꿀 수 있습니다. 라이브러리가 없으면 도전과제 없이 빌드됩니다.

Windows 가상 마이크(VB-CABLE)는 Steam 설치 스크립트를 쓰지 않습니다. 첫 실행 때 STTS가 드라이버가 없음을 확인하고 **가상 마이크 연결 점검** 창을 엽니다. **가상 마이크 설치**를 누르면 관리자 승인 한 번으로 드라이버 설치와 마이크 이름 변경을 마치고, 사용자의 기본 소리 장치를 되돌립니다. 설치 후 PC를 재시작합니다.

## 빌드

Windows:

```powershell
powershell -File Windows/build.ps1 -Steam
```

`Windows/build/steam`에 디포 내용이 생성됩니다. 업로드할 Mac의 같은 경로로 복사합니다. 데모는 `-Demo`를 더해 `Windows/build/steam-demo`에 만듭니다.

macOS:

```sh
bash Support/build-macos.sh
.venv/bin/python Support/package-macos.py --demo-only   # 데모: dist/demo/STTS.app
```

데모는 같은 앱에 데모 표시(Windows `edition.json`, macOS `STTSDemo`)를 붙인 것입니다. 보이스 클론·TTS 단축어·사운드보드·마이크 효과·실시간 자막·모양 꾸미기를 막고, TTS는 기본·낮음 사양만 씁니다. 설정은 정식판과 따로 저장합니다. 소스에서 `STTS_DEMO=1`로 미리 볼 수 있습니다.

## 업로드

```sh
brew install --cask steamcmd
STEAM_APP_ID=앱ID STEAM_DEPOT_WINDOWS=윈도우디포ID STEAM_DEPOT_MAC=맥디포ID STEAM_USER=스팀계정 bash Support/steam-upload.sh
```

`STEAM_PREVIEW=1`을 붙이면 파일 구성만 확인하고 업로드하지 않습니다.

데모:

```sh
STEAM_APP_ID=5369140 STEAM_DEPOT_WINDOWS=5369141 STEAM_DEPOT_MAC=5369142 STEAM_WINDOWS_CONTENT=Windows/build/steam-demo STEAM_MAC_APP=dist/demo/STTS.app STEAM_USER=스팀계정 bash Support/steam-upload.sh
```

## 출시 전 확인

- Steam 라이브러리에서 베타 브랜치로 설치해 첫 실행, 가상 마이크 설치, Discord 입력, STT 자막을 확인합니다.
- 콘텐츠 설문에서 실시간 생성 AI 콘텐츠(TTS·보이스 클론)를 공개합니다.
- 기본 TTS인 gTTS가 입력 문장을 Google에 전송한다는 점을 스토어 설명에 적습니다.
- 유료 판매 시 VB-CABLE 번들 조건을 VB-Audio에 확인합니다.
- Steam으로 제거해도 VB-CABLE 드라이버와 `%LOCALAPPDATA%\STTS`의 사용자 데이터는 남습니다.
