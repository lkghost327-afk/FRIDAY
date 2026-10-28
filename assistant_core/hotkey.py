"""Opt-in Windows shortcut; owns registration on one bounded-lifetime thread."""
import ctypes
import os
import threading


class VoiceHotkey:
    def __init__(self, persona, emit):
        self.persona, self.emit = persona, emit
        self._stop = threading.Event()
        self._thread = None
        self.cancel_enabled = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name='voice-shortcut', daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)

    def _run(self, user32=None):
        if user32 is None:
            if os.name != 'nt':
                return
            user32 = ctypes.windll.user32
        from ctypes import wintypes
        # Ctrl+Alt+F / Ctrl+Alt+A; MOD_NOREPEAT avoids auto-repeat toggling.
        key = ord('A' if self.persona == 'alfred' else 'F')
        registered = []
        for identifier, modifiers in ((1, 0x4003), (2, 0x4007)):
            if user32.RegisterHotKey(None, identifier, modifiers, key):
                registered.append(identifier)
            else:
                self.emit('notice', message=('Talk' if identifier == 1 else 'Dictation') + ' shortcut is already in use. The app buttons remain available.')
        if not registered:
            return
        try:
            message = wintypes.MSG()
            held = set()
            escape_was_down = False
            while not self._stop.wait(.025):
                while user32.PeekMessageW(ctypes.byref(message), None, 0x0312, 0x0312, 1):
                    if message.wParam in registered and not self._stop.is_set():
                        held.add(int(message.wParam))
                        self.emit('voice_shortcut' if message.wParam == 1 else 'dictation_shortcut')
                if held:
                    chord_down = bool(user32.GetAsyncKeyState(key) & 0x8000 and user32.GetAsyncKeyState(0x11) & 0x8000 and user32.GetAsyncKeyState(0x12) & 0x8000)
                    released = {identifier for identifier in held if not chord_down or (identifier == 2 and not user32.GetAsyncKeyState(0x10) & 0x8000)}
                    for identifier in released:
                        self.emit('shortcut_released', shortcut='voice' if identifier == 1 else 'dictation')
                    held.difference_update(released)
                if self.cancel_enabled.is_set():
                    escape_down = bool(user32.GetAsyncKeyState(0x1B) & 0x8000)
                    if escape_down and not escape_was_down:
                        self.emit('voice_cancel')
                    escape_was_down = escape_down
                else:
                    escape_was_down = False
        finally:
            for identifier in registered:
                user32.UnregisterHotKey(None, identifier)
