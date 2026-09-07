"""Windows integration kept separate from audio/model code."""
import ctypes as C
from ctypes import wintypes as W
import os
import subprocess
import sys
import threading

user32 = C.WinDLL('user32', use_last_error=True)
kernel32 = C.WinDLL('kernel32', use_last_error=True)
user32.GetForegroundWindow.restype = W.HWND
user32.GetAncestor.argtypes = [W.HWND, W.UINT]
user32.GetAncestor.restype = W.HWND
user32.SetForegroundWindow.argtypes = [W.HWND]
user32.GetWindowLongPtrW.argtypes = [W.HWND, C.c_int]
user32.GetWindowLongPtrW.restype = C.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [W.HWND, C.c_int, C.c_ssize_t]
user32.SetWindowLongPtrW.restype = C.c_ssize_t
kernel32.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
kernel32.CreateMutexW.restype = W.HANDLE
kernel32.CloseHandle.argtypes = [W.HANDLE]

class SingleInstance:
    def __init__(self):
        self.handle = kernel32.CreateMutexW(None, False, 'Local\\STTS-0.0.1-App')
        if not self.handle:
            raise C.WinError(C.get_last_error())
        self.duplicate = C.get_last_error() == 183

class IO_COUNTERS(C.Structure):
    _fields_ = [(name, C.c_ulonglong) for name in ['ReadOperationCount', 'WriteOperationCount',
        'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount']]
class BASIC_LIMIT(C.Structure):
    _fields_ = [('PerProcessUserTimeLimit', C.c_longlong), ('PerJobUserTimeLimit', C.c_longlong),
        ('LimitFlags', W.DWORD), ('MinimumWorkingSetSize', C.c_size_t), ('MaximumWorkingSetSize', C.c_size_t),
        ('ActiveProcessLimit', W.DWORD), ('Affinity', C.c_size_t), ('PriorityClass', W.DWORD), ('SchedulingClass', W.DWORD)]
class EXTENDED_LIMIT(C.Structure):
    _fields_ = [('BasicLimitInformation', BASIC_LIMIT), ('IoInfo', IO_COUNTERS),
        ('ProcessMemoryLimit', C.c_size_t), ('JobMemoryLimit', C.c_size_t),
        ('PeakProcessMemoryUsed', C.c_size_t), ('PeakJobMemoryUsed', C.c_size_t)]

class ChildJob:
    def __init__(self):
        kernel32.CreateJobObjectW.restype = W.HANDLE
        kernel32.SetInformationJobObject.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]
        kernel32.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
        self.handle = kernel32.CreateJobObjectW(None, None)
        limits = EXTENDED_LIMIT()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not self.handle or not kernel32.SetInformationJobObject(self.handle, 9, C.byref(limits), C.sizeof(limits)):
            raise C.WinError(C.get_last_error())
    def assign(self, proc):
        if not kernel32.AssignProcessToJobObject(self.handle, W.HANDLE(int(proc._handle))):
            proc.kill()
            raise C.WinError(C.get_last_error())
    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

def root_handle(window):
    return user32.GetAncestor(int(window.winId()), 2)

def clickthrough(window):
    hwnd = root_handle(window)
    style = user32.GetWindowLongPtrW(hwnd, -20)
    user32.SetWindowLongPtrW(hwnd, -20, style | 0x20 | 0x08000000 | 0x80)

def foreground(window):
    user32.SetForegroundWindow(root_handle(window))

def set_login(enabled):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        if enabled:
            command = subprocess.list2cmdline([sys.executable])
            if not getattr(sys, 'frozen', False):
                command = subprocess.list2cmdline([sys.executable, os.path.join(os.path.dirname(__file__), 'app.py')])
            winreg.SetValueEx(key, 'STTS', 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, 'STTS')
            except FileNotFoundError:
                pass

def shortcut_data(value):
    if isinstance(value, str):
        return {'keycode': ord(value.upper()), 'modifiers': 3, 'key': value.upper()}
    return value

def shortcut_label(value):
    value = shortcut_data(value)
    return '+'.join([name for bit, name in [(2, 'Ctrl'), (1, 'Alt'), (4, 'Shift'), (8, 'Win')]
                     if value['modifiers'] & bit] + [value['key']])

class HotKeys:
    """RegisterHotKey event loop: no global keyboard recording/hook."""
    def __init__(self, callbacks, report):
        self.callbacks = callbacks
        self.report = report
        self.thread_id = None
        self.errors = []
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        self.ready.wait(2)
        if self.errors:
            self.close()
            raise RuntimeError('\n'.join(self.errors))
    def run(self):
        self.thread_id = kernel32.GetCurrentThreadId()
        msg = W.MSG()
        user32.PeekMessageW(C.byref(msg), None, 0, 0, 0)
        registered = []
        for ident, (shortcut, callback) in self.callbacks.items():
            shortcut = shortcut_data(shortcut)
            if user32.RegisterHotKey(None, ident, 0x4000 | shortcut['modifiers'], shortcut['keycode']):
                registered.append(ident)
            else:
                self.errors.append(f'{shortcut_label(shortcut)} 키를 등록할 수 없습니다. 다른 단축키를 선택해 주세요.')
        self.ready.set()
        while user32.GetMessageW(C.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312 and msg.wParam in self.callbacks:
                self.callbacks[msg.wParam][1]()
        for ident in registered:
            user32.UnregisterHotKey(None, ident)
    def close(self):
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
            self.thread.join(timeout=2)
