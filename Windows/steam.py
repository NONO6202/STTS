"""Unlocks Steam achievements through the Steamworks flat API, then exits."""
import ctypes
import os
from pathlib import Path
import sys
import time

from config import CONTRACT


def library_path():
    folder = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent / 'build'
    return folder / 'steam_api64.dll'


def library():
    return ctypes.CDLL(str(library_path()))


def unlock(ids):
    # The runtime is started by the task scheduler, not Steam, so the helper names its app itself.
    app = str(CONTRACT['steam_app_id'])
    os.environ.setdefault('SteamAppId', app); os.environ.setdefault('SteamGameId', app)
    try: steam = library()
    except OSError: return 2
    steam.SteamAPI_InitFlat.restype = ctypes.c_int; steam.SteamAPI_InitFlat.argtypes = [ctypes.c_char_p]
    steam.SteamAPI_SteamUserStats_v013.restype = ctypes.c_void_p
    steam.SteamAPI_ISteamUserStats_SetAchievement.restype = ctypes.c_bool
    steam.SteamAPI_ISteamUserStats_SetAchievement.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    steam.SteamAPI_ISteamUserStats_StoreStats.restype = ctypes.c_bool
    steam.SteamAPI_ISteamUserStats_StoreStats.argtypes = [ctypes.c_void_p]
    if steam.SteamAPI_InitFlat(ctypes.create_string_buffer(1024)) != 0: return 1
    try:
        stats = steam.SteamAPI_SteamUserStats_v013(); pending = set(ids); deadline = time.monotonic() + 10
        # Setting fails until Steam has sent this user's current stats.
        while pending and time.monotonic() < deadline:
            steam.SteamAPI_RunCallbacks()
            pending = {name for name in pending if not steam.SteamAPI_ISteamUserStats_SetAchievement(stats, name.encode())}
            if pending: time.sleep(.1)
        if pending or not steam.SteamAPI_ISteamUserStats_StoreStats(stats): return 1
        for _ in range(20): steam.SteamAPI_RunCallbacks(); time.sleep(.1)
        return 0
    finally: steam.SteamAPI_Shutdown()
