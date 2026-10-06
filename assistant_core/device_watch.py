"""Windows power/audio notifications; no polling or microphone capture."""
import os
import threading
import time


class DeviceWatch:
    def __init__(self, callback):
        self.callback = callback
        self.closed = threading.Event()
        self.thread = None
        self.hwnd = None
        self._last_resume = 0
        self.ready = threading.Event()
        self.error = None

    def start(self):
        if self.thread is None and os.name == 'nt':
            self.thread = threading.Thread(target=self._run, name='windows-device-watch', daemon=True)
            self.thread.start()

    def close(self):
        self.closed.set()

    def dispatch_power(self, code):
        if self.closed.is_set():
            return
        if code == 4:  # PBT_APMSUSPEND
            self.callback('suspend')
        elif code in {7, 18}:  # User and automatic resume often arrive together.
            now = time.monotonic()
            if now - self._last_resume > 2:
                self._last_resume = now
                self.callback('resume')

    def _run(self):
        import win32api
        import win32gui
        class_name = f'FanAssistantDevices.{os.getpid()}.{id(self)}'
        instance = win32api.GetModuleHandle(None)
        changed = threading.Event()
        enumerator = notification = None
        import comtypes
        comtypes.CoInitialize()
        def procedure(hwnd, message, wparam, lparam):
            if message == 0x218:
                self.dispatch_power(wparam)
                return 1
            return win32gui.DefWindowProc(hwnd, message, wparam, lparam)
        try:
            from pycaw.callbacks import MMNotificationClient
            from pycaw.pycaw import AudioUtilities
            class AudioChanged(MMNotificationClient):
                def on_default_device_changed(self, *args): changed.set()
                def on_device_added(self, *args): changed.set()
                def on_device_removed(self, *args): changed.set()
                def on_device_state_changed(self, *args): changed.set()
                def on_property_value_changed(self, *args): pass
            enumerator = AudioUtilities.GetDeviceEnumerator()
            notification = AudioChanged()
            enumerator.RegisterEndpointNotificationCallback(notification)
            wc = win32gui.WNDCLASS()
            wc.hInstance, wc.lpszClassName, wc.lpfnWndProc = instance, class_name, procedure
            win32gui.RegisterClass(wc)
            self.hwnd = win32gui.CreateWindowEx(0, class_name, '', 0, 0, 0, 0, 0, 0, 0, instance, None)
            self.ready.set()
            next_change, last_tick = 0, time.monotonic()
            while not self.closed.wait(.2):
                win32gui.PumpWaitingMessages()
                now = time.monotonic()
                if now - last_tick > 20:
                    self.dispatch_power(18)
                last_tick = now
                if changed.is_set() and now >= next_change:
                    changed.clear()
                    next_change = now + 2
                    self.callback('audio')
        except Exception as error:
            self.error = type(error).__name__
        finally:
            if enumerator is not None and notification is not None:
                try:
                    enumerator.UnregisterEndpointNotificationCallback(notification)
                except Exception:
                    pass
            notification = enumerator = None
            if self.hwnd:
                win32gui.DestroyWindow(self.hwnd)
                self.hwnd = None
            try:
                win32gui.UnregisterClass(class_name, instance)
            except Exception:
                pass
            comtypes.CoUninitialize()
