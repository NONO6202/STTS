"""Virtual microphone setup for copies not installed by STTS Setup (for example Steam).

Mirrors installer.iss: the signed-in user's default devices are saved and restored around
one elevated step that installs VB-CABLE and gives its capture endpoint the STTS name.
"""
import subprocess
import sys
import time
from pathlib import Path

RESTART = 3010


def base():
    return Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent / 'build/bundle'


def installer():
    return base() / 'VB-CABLE' / 'VBCABLE_Setup_x64.exe'


def _helper(*arguments, timeout=60):
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    return subprocess.run([str(base() / 'STTSMicrophone.exe'), *arguments], cwd=base(), timeout=timeout,
                          capture_output=True, creationflags=flags).returncode


def driver_exists():
    # "--list" fails only when no VB-CABLE capture endpoint exists, including disabled ones.
    try: return _helper('--list') == 0
    except (OSError, subprocess.TimeoutExpired): return False


def install_elevated():
    """Runs as administrator (STTSRuntime.exe --install-driver). Returns a process exit code."""
    installed = False
    if not driver_exists():
        setup = installer()
        if not setup.is_file(): return 2
        subprocess.run([str(setup), '-i', '-h'], cwd=setup.parent, timeout=300, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(30):
            if driver_exists(): break
            time.sleep(1)
        else: return 1
        installed = True
    for _ in range(10):
        if _helper('--rename', str(base() / 'microphone-name.log')) == 0: return RESTART if installed else 0
        time.sleep(1)
    return 1


def _run_elevated(arguments):
    """Starts this executable through UAC and waits; returns its exit code, or None if the user declined."""
    import ctypes
    from ctypes import wintypes

    class Info(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND), ('lpVerb', wintypes.LPCWSTR),
                    ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR), ('lpDirectory', wintypes.LPCWSTR),
                    ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE), ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR),
                    ('hkeyClass', wintypes.HKEY), ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]
    info = Info(cbSize=ctypes.sizeof(Info), fMask=0x40, lpVerb='runas', lpFile=sys.executable,  # SEE_MASK_NOCLOSEPROCESS
                lpParameters=arguments, lpDirectory=str(base()), nShow=0)
    shell32, kernel32 = ctypes.windll.shell32, ctypes.windll.kernel32
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(Info)]
    if not shell32.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess: return None
    try:
        kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        code = wintypes.DWORD(); kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally: kernel32.CloseHandle(info.hProcess)


def setup():
    """Runs as the signed-in user. Returns a message for the connection dialog, or None to re-run its check."""
    if not getattr(sys, 'frozen', False): return 'STTS 설치 EXE를 다시 실행해 가상 마이크를 설치하세요.'
    if not installer().is_file(): return 'STTS 설치 EXE를 다시 실행해 가상 마이크를 설치하세요.'
    preserve = not driver_exists()
    if preserve: _helper('--save-defaults')
    try: code = _run_elevated('--install-driver')
    finally:
        if preserve: _helper('--restore-defaults')
    if code is None: return '설치를 시작하지 못했습니다. 관리자 권한 승인이 필요합니다.'
    if code == RESTART: return '가상 마이크를 설치했습니다. Discord 입력 장치에서 STTS를 선택하세요. 목록에 없으면 Discord를 다시 켜거나 PC를 재시작하세요.'
    if code == 0: return None
    return '가상 마이크 설치를 확인하지 못했습니다. PC를 재시작한 뒤 다시 시도하세요.'
