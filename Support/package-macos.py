"""Package a locally built arm64 app; copy every non-system dylib dependency."""
from pathlib import Path
import importlib.metadata
import json
import os
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
BREW = Path(os.environ.get("HOMEBREW_PREFIX", "/opt/homebrew"))
BUILD = ROOT / ".build"
APP = ROOT / "dist/STTS.app"


def run(*args):
    subprocess.run([str(x) for x in args], check=True)


def dependencies(path):
    text = subprocess.check_output(["otool", "-L", str(path)], text=True)
    return [line.strip().split(" (", 1)[0] for line in text.splitlines()[1:]]


def main():
    if APP.exists():
        shutil.rmtree(APP)
    macos = APP / "Contents/MacOS"
    frameworks = APP / "Contents/Frameworks"
    resources = APP / "Contents/Resources"
    for directory in (macos, frameworks, resources):
        directory.mkdir(parents=True)
    executable = macos / "STTS"
    shutil.copy2(BUILD / "release/STTS", executable)
    product = json.loads((ROOT / "Shared/app.json").read_text())
    with (ROOT / "Support/Info.plist").open("rb") as source:
        info = plistlib.load(source)
    info.update(CFBundleShortVersionString=product["version"], CFBundleVersion=str(product["build"]))
    with (APP / "Contents/Info.plist").open("wb") as output:
        plistlib.dump(info, output)
    shutil.copy2(ROOT / "Shared/app.json", resources / "app.json")
    shutil.copy2(ROOT / "Support/speech_languages.json", resources / "speech_languages.json")
    if "--reuse-workers" not in sys.argv:
        run(ROOT / ".venv/bin/python", "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
            "--name", "gtts-worker", "--distpath", BUILD / "python-dist", "--workpath", BUILD / "python-work",
            "--specpath", BUILD, ROOT / "Support/gtts_worker.py")
        run(ROOT / ".venv/bin/python", "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
            "--name", "mlx-worker", "--distpath", BUILD / "python-dist", "--workpath", BUILD / "python-work-mlx",
            "--specpath", BUILD, "--add-data", str(ROOT / "Support/mlx_models.json") + ":.",
            "--add-data", str(ROOT / "Support/speech_languages.json") + ":.",
            "--collect-all", "mlx", "--collect-data", "mlx_audio", "--copy-metadata", "mlx-audio",
            "--collect-data", "transformers", "--copy-metadata", "transformers", "--copy-metadata", "tokenizers",
            "--hidden-import", "mlx_audio.stt.models.whisper", "--hidden-import", "mlx_audio.tts.models.qwen3_tts",
            "--hidden-import", "mlx_audio.stt.models.qwen3_asr",
            "--hidden-import", "mlx_audio.stt.models.nemotron_asr",
            "--hidden-import", "mlx_audio.tts.models.chatterbox", "--hidden-import", "chatterbox_loader",
            "--hidden-import", "mlx_audio.tts.models.voxcpm2",
            "--collect-all", "supertonic", "--collect-all", "onnxruntime", "--collect-all", "soundfile",
            "--hidden-import", "transformers.models.whisper.processing_whisper",
            "--hidden-import", "transformers.models.whisper.tokenization_whisper",
            "--hidden-import", "transformers.models.whisper.feature_extraction_whisper",
            "--hidden-import", "transformers.models.qwen2.tokenization_qwen2",
            ROOT / "Support/mlx_worker.py")
    shutil.copytree(BUILD / "python-dist/gtts-worker", resources / "gtts-worker", symlinks=True)
    shutil.copytree(BUILD / "python-dist/mlx-worker", resources / "mlx-worker", symlinks=True)
    for bundle in (BUILD / "release").glob("*.bundle"):
        shutil.copytree(bundle, resources / bundle.name)

    copied = {}

    def copy_library(source, name=None):
        name = name or source.name
        if name in copied:
            return
        target = frameworks / name
        shutil.copy2(source.resolve(), target)
        copied[name] = target
        resolve_dependencies(target)

    def resolve_dependencies(target):
        for dep in dependencies(target):
            if dep.startswith(str(BREW)):
                source = Path(dep)
            elif dep.startswith("@rpath/"):
                name = Path(dep).name
                candidates = [BREW / "opt/ggml/lib" / name, BREW / "opt/whisper-cpp/lib" / name, BREW / "opt/libomp/lib" / name]
                source = next((p for p in candidates if p.exists()), None)
                if source is None:
                    raise RuntimeError(f"Unresolved dependency: {dep}")
            else:
                continue
            copy_library(source)
            run("install_name_tool", "-change", dep, "@rpath/" + source.name, target)

    resolve_dependencies(executable)
    for backend in (BREW / "opt/ggml/libexec").glob("*.so"):
        copy_library(backend)
    commands = subprocess.check_output(["otool", "-l", str(executable)], text=True).splitlines()
    for index, line in enumerate(commands):
        if "cmd LC_RPATH" in line:
            rpath = commands[index + 2].strip().split(" (offset", 1)[0].removeprefix("path ")
            if rpath.startswith((str(ROOT), "/Library/Developer/")):
                run("install_name_tool", "-delete_rpath", rpath, executable)
    run("install_name_tool", "-add_rpath", "@executable_path/../Frameworks", executable)
    for name, library in copied.items():
        if name.endswith(".dylib"):
            run("install_name_tool", "-id", "@rpath/" + name, library)
        run("install_name_tool", "-add_rpath", "@loader_path", library)
        run("codesign", "--force", "--sign", "-", library)

    licenses = resources / "Licenses"
    licenses.mkdir()
    native = {
        "whisper.cpp": BREW / "opt/whisper-cpp/LICENSE",
        "ggml": BREW / "opt/ggml/LICENSE",
        "libomp": BREW / "opt/libomp/LICENSE.TXT",
        "FluidAudio": BUILD / "checkouts/FluidAudio/LICENSE",
    }
    for name, path in native.items():
        shutil.copy2(path, licenses / (name + ".txt"))
    for dist in importlib.metadata.distributions():
        for file in dist.files or []:
            if any(word in file.name.lower() for word in ("license", "copying", "notice")):
                source = Path(dist.locate_file(file))
                if source.is_file() and source.suffix != ".py":
                    target = licenses / dist.metadata["Name"] / str(file)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    python_license = BREW / "opt/python@3.14/Frameworks/Python.framework/Versions/3.14/Resources/LICENSE.txt"
    if python_license.exists():
        shutil.copy2(python_license, licenses / "Python-PSF.txt")
    shutil.copy2(ROOT / "Support/THIRD_PARTY.md", licenses / "THIRD_PARTY.md")
    for source in (ROOT / "Support/Licenses").glob("*"):
        shutil.copy2(source, licenses / source.name)
    # PyInstaller signs its interpreter. Sign nested bundle and then the outer app.
    run("codesign", "--force", "--deep", "--sign", "-", APP)
    run("codesign", "--verify", "--deep", "--strict", APP)
    for target in APP.rglob("*"):
        if target.is_file() and not target.is_symlink():
            with target.open("rb") as handle:
                magic = handle.read(4)
            if magic not in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
                continue
            if any(dep.startswith(str(BREW)) for dep in dependencies(target)):
                raise RuntimeError("Non-portable Homebrew link remains: " + str(target))
    staging = BUILD / "dmg-root"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    shutil.copytree(APP, staging / APP.name, symlinks=True)
    (staging / "Applications").symlink_to("/Applications")
    shutil.copy2(ROOT / "README.md", staging / "읽어주세요.md")
    version = plistlib.loads((APP / "Contents/Info.plist").read_bytes())["CFBundleShortVersionString"]
    run("hdiutil", "create", "-volname", "STTS", "-srcfolder", staging, "-ov", "-format", "UDZO", ROOT / f"dist/STTS-{version}-arm64.dmg")
    print(APP)


if __name__ == "__main__":
    main()
