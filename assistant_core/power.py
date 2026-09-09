"""Cancellable local power countdowns; no force-close flags or arbitrary commands."""
import ctypes
import os
from pathlib import Path
import subprocess
import threading


class PowerControl:
    def __init__(self, emit):
        self.emit = emit
        self._lock = threading.Lock()
        self._pending = None

    def cancel(self):
        with self._lock:
            pending, self._pending = self._pending, None
            if pending:
                pending.set()
        return "Cancelled the pending power action." if pending else "There is no pending power action."

    def request(self, action):
        if action not in {"shutdown", "restart", "sleep", "lock"}:
            raise ValueError("Choose shutdown, restart, sleep, or lock.")
        self.cancel()
        token = threading.Event()
        with self._lock:
            self._pending = token
        def run():
            if token.wait(10):
                return
            with self._lock:
                if self._pending is not token:
                    return
                self._pending = None
            try:
                self._perform(action)
            except Exception:
                self.emit("notice", message="Windows could not complete the power action. Check your device's power options.")
        threading.Thread(target=run, name="assistant-power", daemon=True).start()
        return f"{action.capitalize()} in 10 seconds. Say cancel or press Stop."

    @staticmethod
    def _perform(action):
        if action in {"shutdown", "restart"}:
            # A positive shutdown.exe timeout implies /f on Windows. Use our own
            # countdown, then /t 0, so unsaved applications may block shutdown.
            executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/shutdown.exe"
            subprocess.run([str(executable), "/s" if action == "shutdown" else "/r", "/t", "0"],
                           check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        elif action == "lock":
            if not ctypes.windll.user32.LockWorkStation():
                raise OSError("Lock request failed")
        elif action == "sleep":
            import win32api
            import win32con
            import win32security
            token = win32security.OpenProcessToken(win32api.GetCurrentProcess(),
                win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY)
            previous = None
            try:
                privilege = win32security.LookupPrivilegeValue(None, win32security.SE_SHUTDOWN_NAME)
                previous = win32security.AdjustTokenPrivileges(token, False, [(privilege, win32con.SE_PRIVILEGE_ENABLED)])
                suspend = ctypes.windll.powrprof.SetSuspendState
                suspend.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ubyte]
                suspend.restype = ctypes.c_ubyte
                if not suspend(False, False, False):
                    raise OSError("Sleep request failed")
            finally:
                if previous is not None:
                    win32security.AdjustTokenPrivileges(token, False, previous)
                token.Close()
