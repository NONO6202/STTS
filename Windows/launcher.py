"""Steam and desktop shortcuts start this short-lived controller."""
import ctypes
from pathlib import Path
import subprocess
import sys

import runtime
from localization import tr, message


def main():
    arguments = sys.argv[1:]
    if '--steam-achievements' in arguments:
        # A background helper: failures are reported by exit code, never by a dialog.
        try:
            from steam import unlock
            return unlock(arguments[arguments.index('--steam-achievements') + 1:])
        except Exception: return 1
    try:
        if any(flag in arguments for flag in ('--smoke-test', '--verify-install', '--diagnose-audio', '--install-driver')):
            if getattr(sys, 'frozen', False): command = [str(Path(sys.executable).with_name('STTSRuntime.exe'))]
            else: command = [sys.executable, str(Path(__file__).with_name('app.py'))]
            return subprocess.call(command + arguments)
        if '--unregister-runtime' in arguments: runtime.unregister(); return 0
        if '--restart' in arguments:
            # Wait for the old runtime process to exit so the scheduled task can start a new one.
            pid = int(arguments[arguments.index('--restart') + 1])
            handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
            if handle: ctypes.windll.kernel32.WaitForSingleObject(handle, 15000); ctypes.windll.kernel32.CloseHandle(handle)
            runtime.launch(); return 0
        for command in ('status', 'hide', 'quit'):
            if '--' + command in arguments:
                return 0 if runtime.request(command) is not None else 1
        runtime.launch(show='--background' not in arguments)
        return 0
    except Exception as error:
        ctypes.windll.user32.MessageBoxW(None, tr('STTS를 시작하지 못했습니다. 다시 실행해 주세요.') + '\n\n' + message(str(error)), 'STTS', 0x10)
        return 1


if __name__ == '__main__': raise SystemExit(main())
