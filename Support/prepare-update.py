"""Create signed update assets locally; does not publish or change GitHub state."""
from pathlib import Path
import argparse
import plistlib
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / '.build/artifacts/sparkle/Sparkle/bin'
ACCOUNT = 'local.stts.mac'
REPOSITORY = 'NONO6202/STTS'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, default=ROOT / 'dist/STTS.app',
                        help='App to sign for updating, including an app mounted from a verified DMG')
    parser.add_argument('--output', type=Path,
                        help='Fresh output directory for rebuilding an existing release without overwriting prior assets')
    args = parser.parse_args()
    app = args.app.resolve()
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    version = info['CFBundleShortVersionString']
    if not version or any(c not in '0123456789.' for c in version):
        raise ValueError('Invalid release version')
    expected_feed = f'https://github.com/{REPOSITORY}/releases/latest/download/appcast.xml'
    if info.get('SUFeedURL') != expected_feed:
        raise ValueError('The app feed URL does not match the release repository')
    public_key = subprocess.check_output([TOOLS / 'generate_keys', '--account', ACCOUNT, '-p'], text=True).strip()
    if public_key != info['SUPublicEDKey']:
        raise ValueError('The signing key does not match the public key embedded in the app')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', app], check=True)
    output = args.output.resolve() if args.output else ROOT / 'dist/updates' / version
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f'STTS-{version}-arm64.zip'
    if archive.exists():
        raise FileExistsError(f'Update already prepared: {output}. Choose a fresh --output directory.')
    subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', app, archive], check=True)
    prefix = f'https://github.com/{REPOSITORY}/releases/download/v{version}/'
    subprocess.run([TOOLS / 'generate_appcast', '--account', ACCOUNT, '--maximum-deltas', '0',
                    '--download-url-prefix', prefix, output], check=True)
    feed = output / 'appcast.xml'
    subprocess.run([TOOLS / 'sign_update', '--account', ACCOUNT, '--verify', feed], check=True)
    item = ET.parse(feed).find('channel/item')
    enclosure = item.find('enclosure')
    if enclosure.attrib['url'] != prefix + archive.name:
        raise ValueError('Unexpected update archive URL')
    signature = enclosure.attrib['{http://www.andymatuschak.org/xml-namespaces/sparkle}edSignature']
    subprocess.run([TOOLS / 'sign_update', '--account', ACCOUNT, '--verify', archive, signature], check=True)
    print(f'Ready: {archive}\nReady: {feed}')
    print(f'After the repository is public, attach both files to the latest non-prerelease release v{version} in {REPOSITORY}.')


if __name__ == '__main__':
    main()
