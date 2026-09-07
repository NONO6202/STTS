# 소스 빌드

## Windows

필요 도구: Python 3.13 x64, Visual Studio C++ Build Tools, Inno Setup 6.

```powershell
powershell -File Windows/build.ps1
powershell -File Windows/verify.ps1
```

설치 파일은 `dist/`에 생성됩니다. 검증은 별도 데이터 폴더와 기본 Windows PATH에서 패키지 EXE로 수행합니다.

## macOS

필요 도구: macOS 26+, Apple Silicon, Xcode Command Line Tools, Homebrew.

```sh
brew install uv python whisper-cpp ggml libomp
bash Support/build-macos.sh
```

`dist/STTS.app`과 DMG를 생성합니다. 자동 업데이트용 서명 파일은 해당 키가 있는 Mac에서 `Support/prepare-update.py`로 생성합니다.

## 테스트

```powershell
Windows/build-env/Scripts/python.exe -m unittest discover -s Tests -p "test_windows*.py"
Windows/build-env/Scripts/python.exe -m unittest discover -s Tests -p "test_tts_phrases.py"
```

[Windows 검증 범위](verification.md)
