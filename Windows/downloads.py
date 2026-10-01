"""Bounded parallel, resumable downloads for pinned model assets."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import ssl
import threading
import urllib.request
import time


def download(url, destination, size, progress):
    import certifi
    context = ssl.create_default_context(cafile=certifi.where())
    destination = Path(destination)
    parts = destination.with_name('.' + destination.name + '.parts')
    parts.mkdir(exist_ok=True)
    chunk_size = 16 * 1024 * 1024
    count = (size + chunk_size - 1) // chunk_size
    completed = [0]; lock = threading.Lock()
    def fetch(index):
        start, end = index * chunk_size, min(size, (index + 1) * chunk_size) - 1
        path = parts / str(index)
        if not path.is_file() or path.stat().st_size != end-start+1:
            temporary = path.with_suffix('.partial')
            for attempt in range(3):
                try:
                    request = urllib.request.Request(url, headers={'Range': f'bytes={start}-{end}'})
                    with urllib.request.urlopen(request, context=context, timeout=45) as response, temporary.open('wb') as output:
                        if response.status == 206:
                            if response.headers.get('Content-Range') != f'bytes {start}-{end}/{size}':
                                raise ValueError('모델 다운로드 범위가 잘못되었습니다.')
                        elif response.status != 200 or count != 1:
                            raise ValueError('서버가 모델 이어받기를 지원하지 않습니다.')
                        received = 0
                        while data := response.read(min(1024 * 1024, end-start+2-received)):
                            output.write(data); received += len(data)
                            if received > end-start+1: raise ValueError('모델 파일 크기가 다릅니다.')
                    if received != end-start+1: raise ValueError('모델 다운로드가 중단되었습니다.')
                    os.replace(temporary, path)
                    break
                except (OSError, ValueError):
                    temporary.unlink(missing_ok=True)
                    if attempt == 2: raise
                    time.sleep(attempt + 1)
        with lock:
            completed[0] += end-start+1
            progress(completed[0])
    with ThreadPoolExecutor(max_workers=min(6, count)) as executor:
        list(executor.map(fetch, range(count)))
    temporary = destination.with_name('.' + destination.name + '.download')
    with temporary.open('wb') as output:
        for index in range(count):
            with (parts / str(index)).open('rb') as source:
                while data := source.read(4 * 1024 * 1024): output.write(data)
    return temporary, parts, count


def finish_parts(parts, count):
    for index in range(count): (parts / str(index)).unlink(missing_ok=True)
    try: parts.rmdir()
    except OSError: pass
