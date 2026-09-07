"""Windows release selection and verified installer downloads."""
import hashlib
import json
from pathlib import Path
import re
import ssl
import urllib.request

RELEASES = 'https://api.github.com/repos/NONO6202/STTS/releases?per_page=100'
DOWNLOADS = 'https://github.com/NONO6202/STTS/releases/download/'


def version_tuple(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value)
    return tuple(map(int, match.groups())) if match else None


def select_release(releases, current):
    candidates = []
    for release in releases:
        version = version_tuple(release.get('tag_name', ''))
        if release.get('draft') or release.get('prerelease') or not version or version <= version_tuple(current):
            continue
        tag = release['tag_name']
        name = f'STTS-{tag.lstrip("v")}-setup-x64.exe'
        for asset in release.get('assets', []):
            url = asset.get('browser_download_url', '')
            if asset.get('name') == name and url == f'{DOWNLOADS}{tag}/{name}':
                candidates.append((version, dict(asset, version=tag.lstrip('v'))))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def open_url(url, version):
    import certifi
    request = urllib.request.Request(url, headers={
        'User-Agent': 'STTS-Windows/' + version, 'Accept': 'application/vnd.github+json'})
    return urllib.request.urlopen(request, timeout=30,
        context=ssl.create_default_context(cafile=certifi.where()))


def check_update(current):
    with open_url(RELEASES, current) as response:
        releases = json.load(response)
    return select_release(releases, current)


def download_installer(asset, directory, current, progress):
    digest = asset.get('digest', '')
    if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
        raise ValueError('배포 파일의 SHA-256 정보가 없습니다. GitHub 릴리스를 확인하세요.')
    name = f'STTS-{asset["version"]}-setup-x64.exe'
    if asset['name'] != name or not asset['browser_download_url'].startswith(DOWNLOADS):
        raise ValueError('업데이트 파일 주소가 올바르지 않습니다.')
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    destination = directory / name
    temporary = destination.with_suffix('.part')
    size = 0; checksum = hashlib.sha256()
    try:
        with open_url(asset['browser_download_url'], current) as response, temporary.open('wb') as output:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > asset['size']:
                    raise ValueError('업데이트 파일 크기가 배포 정보와 다릅니다.')
                output.write(chunk); checksum.update(chunk)
                progress(size, asset['size'])
        if size != asset['size'] or checksum.hexdigest() != digest.split(':', 1)[1].lower():
            raise ValueError('업데이트 파일 검증에 실패했습니다. 다시 다운로드하세요.')
        temporary.replace(destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)
