"""One running window per persona, with a launch-again signal for tray restore."""
import ctypes
from ctypes import wintypes
import sys


class SingleInstance:
    def __init__(self, persona, show_existing=True):
        self.primary = True
        self.mutex = self.event = None
        if sys.platform != "win32":
            return
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateEventW.restype = wintypes.HANDLE
        for name in ("CloseHandle", "SetEvent"):
            getattr(self.kernel, name).argtypes = [wintypes.HANDLE]
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.mutex = self.kernel.CreateMutexW(None, False, "Local\\FanAssistants." + persona)
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        self.primary = ctypes.get_last_error() != 183
        self.event = self.kernel.CreateEventW(None, False, False, "Local\\FanAssistants.Show." + persona)
        if not self.event:
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        if not self.primary and show_existing:
            self.kernel.SetEvent(self.event)

    def show_requested(self):
        return bool(self.event and self.kernel.WaitForSingleObject(self.event, 0) == 0)

    def close(self):
        for name in ("event", "mutex"):
            handle = getattr(self, name, None)
            if handle:
                self.kernel.CloseHandle(handle)
                setattr(self, name, None)
