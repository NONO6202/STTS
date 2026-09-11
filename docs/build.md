# 소스 빌드

## Windows

필요 도구: Python 3.13 x64, Visual Studio C++ Build Tools, Inno Setup 6.

```powershell
powershell -File Windows/build.ps1
```

설치 파일은 `dist/`에 생성됩니다.

## macOS

필요 도구: macOS 26+, Apple Silicon, Xcode Command Line Tools, Homebrew.

```sh
brew install uv python whisper-cpp ggml libomp
bash Support/build-macos.sh
```

`dist/STTS.app`과 DMG를 로컬에 생성합니다. GitHub에는 실행 파일을 업로드하지 않습니다.

GitHub Actions 빌드·검증은 수동 실행하며, 설치 파일과 검증 산출물을 GitHub에 업로드하지 않습니다.
