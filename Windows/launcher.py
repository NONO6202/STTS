"""Steam and desktop shortcuts start this short-lived controller."""
import ctypes
from pathlib import Path
import subprocess
import sys

import runtime
from localization import tr, message


def main():
    arguments = sys.argv[1:]
    try:
        if any(flag in arguments for flag in ('--smoke-test', '--verify-install', '--diagnose-audio', '--install-driver')):
            if getattr(sys, 'frozen', False): command = [str(Path(sys.executable).with_name('STTSRuntime.exe'))]
            else: command = [sys.executable, str(Path(__file__).with_name('app.py'))]
            return subprocess.call(command + arguments)
        if '--unregister-runtime' in arguments: runtime.unregister(); return 0
        for command in ('status', 'hide', 'quit'):
            if '--' + command in arguments:
                return 0 if runtime.request(command) is not None else 1
        runtime.launch(show='--background' not in arguments)
        return 0
    except Exception as error:
        ctypes.windll.user32.MessageBoxW(None, tr('STTS를 시작하지 못했습니다. 다시 실행해 주세요.') + '\n\n' + message(str(error)), 'STTS', 0x10)
        return 1


if __name__ == '__main__': raise SystemExit(main())
