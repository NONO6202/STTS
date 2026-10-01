import importlib.metadata
from pathlib import Path
import shutil
import sys
root = Path(sys.argv[1]); root.mkdir(parents=True, exist_ok=True)
index = []
for dist in importlib.metadata.distributions():
    name = dist.metadata['Name']
    if name.lower() in ('pip', 'setuptools'): continue
    index.append(f"{name} {dist.version}: {dist.metadata.get('License-Expression') or dist.metadata.get('License', 'See package license files')}\n")
    for file in dist.files or []:
        if any(word in str(file).lower() for word in ('license', 'copying', 'notice')) and str(file).lower().endswith(('.txt', '.md', 'license', 'copying', 'notice')):
            source = Path(dist.locate_file(file))
            if source.is_file():
                if Path(file).is_absolute() or '..' in Path(file).parts: continue
                dest = root / name / Path(file)
                dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, dest)
(root / 'PACKAGES.txt').write_text('\n'.join(index), encoding='utf-8')
for source in (Path(__file__).resolve().parent.parent / 'Support' / 'Licenses').glob('*'):
    if source.name.startswith(('Qwen3-TTS-', 'Whisper-model-', 'Supertonic3-', 'Python-', 'Silero-')):
        shutil.copy2(source, root / source.name)
shutil.copy2(Path(__file__).parent / 'VB-CABLE-NOTICE.txt', root)
