"""The per-user Task Scheduler runtime and its local control channel."""
import csv
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from config import DEFAULTS, VERSION, CONTRACT, data_directory


def system_command(name, arguments):
    executable = Path(os.environ['SystemRoot']) / 'System32' / name
    return subprocess.run([str(executable), *arguments], capture_output=True, text=True,
                          creationflags=subprocess.CREATE_NO_WINDOW)


def user_sid():
    result = system_command('whoami.exe', ['/user', '/fo', 'csv', '/nh'])
    if result.returncode: raise RuntimeError(result.stderr.strip())
    sid = next(csv.reader(result.stdout.splitlines()))[-1]
    if not sid.startswith('S-1-') or not all(part.isdigit() for part in sid.split('-')[1:]):
        raise RuntimeError('Invalid user SID')
    return sid


def control_name(sid=None):
    suffix = (sid or user_sid())
    if 'STTS_DATA_DIR' in os.environ:
        suffix += '-' + hashlib.sha256(str(data_directory()).casefold().encode()).hexdigest()[:12]
    return 'STTSRuntime-' + suffix


class RuntimeInstance:
    def __init__(self, name):
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
        self.kernel.CreateMutexW.restype = W.HANDLE
        self.kernel.CloseHandle.argtypes = [W.HANDLE]
        self.handle = self.kernel.CreateMutexW(None, False, 'Global' + chr(92) + name)
        if not self.handle: raise C.WinError(C.get_last_error())
        self.duplicate = C.get_last_error() == 183

    def close(self):
        if self.handle: self.kernel.CloseHandle(self.handle); self.handle = None

    def __del__(self): self.close()


def runtime_command():
    if getattr(sys, 'frozen', False):
        root = Path(sys.executable).parent
        return [str(root / 'STTSRuntime.exe'), '--background-runtime']
    return [sys.executable, str(Path(__file__).with_name('app.py')), '--background-runtime']


def task_xml(sid, command, login):
    ET.register_namespace('', 'http://schemas.microsoft.com/windows/2004/02/mit/task')
    namespace = '{http://schemas.microsoft.com/windows/2004/02/mit/task}'
    root = ET.Element(namespace + 'Task', {'version': '1.2'})
    def add(parent, name, text=None, **attributes):
        node = ET.SubElement(parent, namespace + name, attributes)
        node.text = text
        return node
    triggers = add(root, 'Triggers')
    if login:
        trigger = add(triggers, 'LogonTrigger'); add(trigger, 'Enabled', 'true'); add(trigger, 'UserId', sid)
    principal = add(add(root, 'Principals'), 'Principal', id='User')
    add(principal, 'UserId', sid); add(principal, 'LogonType', 'InteractiveToken'); add(principal, 'RunLevel', 'LeastPrivilege')
    settings = add(root, 'Settings')
    for name, value in [('MultipleInstancesPolicy', 'IgnoreNew'), ('DisallowStartIfOnBatteries', 'false'),
                        ('StopIfGoingOnBatteries', 'false'), ('AllowStartOnDemand', 'true'),
                        ('Enabled', 'true'), ('ExecutionTimeLimit', 'PT0S')]: add(settings, name, value)
    action = add(add(root, 'Actions', Context='User'), 'Exec')
    add(action, 'Command', command[0]); add(action, 'Arguments', subprocess.list2cmdline(command[1:]))
    add(action, 'WorkingDirectory', str(Path(command[0]).parent))
    return ET.tostring(root, encoding='utf-16', xml_declaration=True)


def configure(login, sid=None):
    sid = sid or user_sid()
    folder = data_directory() / 'Runtime'; folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'task.xml'; data = task_xml(sid, runtime_command(), login)
    name = 'STTS Background ' + sid
    exists = system_command('schtasks.exe', ['/Query', '/TN', name]).returncode == 0
    if not exists or not path.exists() or path.read_bytes() != data:
        temporary = path.with_suffix('.tmp'); temporary.write_bytes(data)
        result = system_command('schtasks.exe', ['/Create', '/TN', name, '/XML', str(temporary), '/F'])
        if result.returncode:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        os.replace(temporary, path)
    # The old registry startup launched a Steam-owned executable directly.
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        try: winreg.DeleteValue(key, 'STTS')
        except FileNotFoundError: pass
    return name


def set_login(enabled):
    configure(enabled)


def request(command, sid=None, timeout=2):
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
    kernel.CreateFileW.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.WaitNamedPipeW.argtypes = [W.LPCWSTR, W.DWORD]
    kernel.ReadFile.argtypes = [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]
    kernel.WriteFile.argtypes = kernel.ReadFile.argtypes
    kernel.PeekNamedPipe.argtypes = [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.POINTER(W.DWORD), C.POINTER(W.DWORD)]
    path = '\\\\.\\pipe\\' + control_name(sid)
    if not kernel.WaitNamedPipeW(path, 100):
        if C.get_last_error() in (2, 121, 231): return None
        raise C.WinError(C.get_last_error())
    handle = kernel.CreateFileW(path, 0xC0000000, 0, None, 3, 0, None)
    if handle == W.HANDLE(-1).value: return None
    try:
        data = json.dumps({'command': command}).encode() + b'\n'; written = W.DWORD()
        if not kernel.WriteFile(handle, data, len(data), C.byref(written), None): return None
        deadline = time.monotonic() + timeout; response = bytearray()
        while time.monotonic() < deadline and len(response) < 4096:
            available = W.DWORD()
            if not kernel.PeekNamedPipe(handle, None, 0, None, C.byref(available), None): return None
            if available.value:
                buffer = C.create_string_buffer(min(available.value, 4096 - len(response))); read = W.DWORD()
                if not kernel.ReadFile(handle, buffer, len(buffer), C.byref(read), None): return None
                response.extend(buffer.raw[:read.value])
                if b'\n' in response: return json.loads(response)
            else: time.sleep(0.01)
        return None
    finally: kernel.CloseHandle(handle)


def outdated(response, build=None):
    running = response.get('build')
    return isinstance(running, int) and running != (CONTRACT['build'] if build is None else build)


def replace(response, sid=None, timeout=10):
    """Quit the old runtime and wait for its process, which still owns the pipe and mutex, to exit."""
    pid = response.get('pid')
    if not isinstance(pid, int) or pid <= 0: return False
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = W.HANDLE
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    request('quit', sid)
    if not handle: return request('status', sid) is None
    try: return kernel.WaitForSingleObject(W.HANDLE(handle), int(timeout * 1000)) == 0
    finally: kernel.CloseHandle(W.HANDLE(handle))


def launch(show=True):
    sid = user_sid()
    try: settings = json.loads((data_directory() / 'settings.json').read_text(encoding='utf-8'))
    except (OSError, ValueError): settings = {}
    name = configure(bool(settings.get('setup_completed') and settings.get('login', DEFAULTS['login'])), sid)
    command = 'show' if show else 'status'
    running = request('status', sid)
    if running is not None:
        # Steam replaces files under a runtime that keeps running; restart one from another build.
        # If the old build will not exit, keep using it rather than failing to open.
        if not outdated(running) or not replace(running, sid):
            if not show or request('show', sid) is not None: return
    result = system_command('schtasks.exe', ['/Run', '/TN', name])
    if result.returncode: raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if request(command, sid) is not None: return
        time.sleep(0.1)
    raise RuntimeError('STTS를 시작하지 못했습니다. 다시 실행해 주세요.')


def unregister():
    sid = user_sid(); request('quit', sid)
    result = system_command('schtasks.exe', ['/Delete', '/TN', 'STTS Background ' + sid, '/F'])
    if result.returncode and system_command('schtasks.exe', ['/Query', '/TN', 'STTS Background ' + sid]).returncode == 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    (data_directory() / 'Runtime/task.xml').unlink(missing_ok=True)
