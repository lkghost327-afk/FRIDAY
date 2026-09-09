"""System tray and no-focus wake overlay for the desktop assistant.

The tray library owns a native worker thread.  Its callbacks only enqueue
commands; :class:`AssistantWindow` consumes them from Tk's main thread.
Importing this module has no optional-dependency or desktop side effects.
"""

from __future__ import annotations

import math
import queue
import sys
import threading
import time
import tkinter as tk


TRANSPARENT = "#010203"


def _mix(first: str, second: str, amount: float) -> str:
    amount = max(0.0, min(1.0, amount))
    a = tuple(int(first[index:index + 2], 16) for index in (1, 3, 5))
    b = tuple(int(second[index:index + 2], 16) for index in (1, 3, 5))
    return "#" + "".join(
        f"{round(x * amount + y * (1 - amount)):02x}" for x, y in zip(a, b)
    )


class SystemTray:
    """Small pystray adapter whose callbacks never access Tk directly."""

    def __init__(self, name: str, accent: str, persona: str):
        self.name = str(name)
        self.accent = accent
        self.persona = persona
        self.commands: queue.Queue[str] = queue.Queue()
        self._lock = threading.RLock()
        self._speech_enabled = True
        self._wake_enabled = False
        self._icon = None
        self.available = False

    def _dispatch(self, command: str) -> None:
        self.commands.put(command)

    def get_nowait(self) -> str:
        return self.commands.get_nowait()

    def set_state(self, *, speech_enabled=None, wake_enabled=None) -> None:
        with self._lock:
            if speech_enabled is not None:
                self._speech_enabled = bool(speech_enabled)
            if wake_enabled is not None:
                self._wake_enabled = bool(wake_enabled)
            icon = self._icon
        if icon is not None:
            try:
                icon.update_menu()
            except Exception:
                pass

    def _speech_checked(self, __item=None) -> bool:
        with self._lock:
            return self._speech_enabled

    def _wake_checked(self, _item=None) -> bool:
        with self._lock:
            return self._wake_enabled

    def _speech_label(self, _item=None) -> str:
        return "Mute spoken replies" if self._speech_checked() else "Unmute spoken replies"

    def start(self) -> bool:
        """Start the native icon if pystray and Pillow are available."""
        try:
            import pystray
            from PIL import Image, ImageDraw

            color = tuple(int(self.accent[index:index + 2], 16) for index in (1, 3, 5))
            image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse((5, 5, 59, 59), outline=(*color, 150), width=3)
            draw.ellipse((13, 13, 51, 51), fill=(8, 13, 19, 255), outline=(*color, 235), width=3)
            draw.ellipse((23, 23, 41, 41), fill=(*color, 255))

            menu = pystray.Menu(
                pystray.MenuItem("Show", lambda _icon, _item: self._dispatch("show"), default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    self._speech_label,
                    lambda _icon, _item: self._dispatch("toggle_speech"),
                    checked=self._speech_checked,
                ),
                pystray.MenuItem(
                    "Wake listening",
                    lambda _icon, _item: self._dispatch("toggle_wake"),
                    checked=self._wake_checked,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", lambda _icon, _item: self._dispatch("exit")),
            )
            icon = pystray.Icon(
                f"fan-assistant-{self.persona}", image, f"{self.name} · Desktop assistant", menu
            )
            with self._lock:
                self._icon = icon
            icon.run_detached()
            self.available = True
            return True
        except Exception:
            with self._lock:
                self._icon = None
            self.available = False
            return False

    def stop(self) -> None:
        with self._lock:
            icon, self._icon = self._icon, None
        self.available = False
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass


class WakeOverlay(tk.Toplevel):
    """A tiny animated indicator that stays out of the user's focus path."""

    WIDTH = 100
    HEIGHT = 92

    def __init__(self, parent, accent: str, name: str):
        super().__init__(parent)
        self.accent = accent
        self.name = name
        self._active = False
        self._closed = False
        self._phase = "listening"
        self._detail = "LISTENING"
        self._angle = 0.0
        self._fade_started = None
        self._last_activity = time.monotonic()
        self._animation_handle = None

        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=TRANSPARENT)
        try:
            self.attributes("-topmost", True)
            self.attributes("-alpha", 0.0)
            if sys.platform == "win32":
                self.attributes("-transparentcolor", TRANSPARENT)
                self.attributes("-disabled", True)
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(
            self, width=self.WIDTH, height=self.HEIGHT, bg=TRANSPARENT,
            highlightthickness=0, borderwidth=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self._position()

    @property
    def active(self) -> bool:
        return self._active

    def _position(self) -> None:
        left = self.winfo_screenwidth() - self.WIDTH - 22
        top = self.winfo_screenheight() - self.HEIGHT - 62
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                work = wintypes.RECT()
                if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(work), 0):
                    left = work.right - self.WIDTH - 18
                    top = work.bottom - self.HEIGHT - 18
            except Exception:
                pass
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}+{max(0, left)}+{max(0, top)}")

    def _apply_no_activate_style(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            get_style = ctypes.windll.user32.GetWindowLongW
            set_style = ctypes.windll.user32.SetWindowLongW
            style = get_style(hwnd, -20)
            set_style(hwnd, -20, style | 0x00000080 | 0x08000000)
            ctypes.windll.user32.SetWindowPos(
                hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040
            )
        except Exception:
            pass

    def show(self, phase="listening", detail="") -> None:
        if self._closed:
            return
        self._phase = str(phase or "listening").lower()
        self._detail = str(detail or self._phase).upper()
        self._active = True
        self._fade_started = None
        self._last_activity = time.monotonic()
        self._position()
        self.update_idletasks()
        self._apply_no_activate_style()
        self.deiconify()
        try:
            self.attributes("-alpha", 1.0)
        except tk.TclError:
            pass
        self.update_idletasks()
        self._apply_no_activate_style()
        if self._animation_handle is None:
            self._animate()

    def set_phase(self, phase: str, detail="") -> None:
        if self._active:
            self._last_activity = time.monotonic()
            self._phase = str(phase or "thinking").lower()
            self._detail = str(detail or self._phase).upper()

    def fade(self) -> None:
        if self._active and self._fade_started is None:
            self._fade_started = time.monotonic()

    def hide(self) -> None:
        self._active = False
        self._fade_started = None
        try:
            self.withdraw()
        except tk.TclError:
            pass

    def _animate(self) -> None:
        self._animation_handle = None
        if self._closed or not self._active:
            return
        self._angle += 0.16 if self._phase == "thinking" else 0.10
        pulse = (math.sin(self._angle * 2.4) + 1.0) / 2.0
        canvas = self.canvas
        canvas.delete("all")
        cx, cy = 50, 37
        dim = _mix(self.accent, "#081019", 0.40)
        for index, radius in enumerate((18 + pulse * 3, 25 + pulse * 4, 32 + pulse * 3)):
            canvas.create_oval(
                cx - radius, cy - radius, cx + radius, cy + radius,
                outline=_mix(self.accent, TRANSPARENT, 0.68 - index * 0.13),
                width=2 if index == 0 else 1,
            )
        if self._phase == "thinking":
            rotation = math.degrees(self._angle) % 360
            for offset in (0, 120, 240):
                canvas.create_arc(
                    cx - 25, cy - 25, cx + 25, cy + 25,
                    start=rotation + offset, extent=48, style="arc", outline=self.accent, width=3,
                )
        elif self._phase == "speaking":
            for index, x in enumerate((-11, -4, 4, 11)):
                height = 6 + 9 * (math.sin(self._angle * 3 + index) + 1) / 2
                canvas.create_line(cx + x, cy - height, cx + x, cy + height,
                                   fill=self.accent, width=3)
        if self._phase != "speaking":
            radius = 8 + pulse * 2
            canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill=dim, outline=self.accent, width=2)
            canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill="#F4FDFF", outline="")
        phase_text = {
            "listening": "LISTENING", "transcribing": "HEARD YOU",
            "thinking": "THINKING", "speaking": "SPEAKING",
        }.get(self._phase, self._detail[:24])
        canvas.create_text(cx, 81, text=phase_text,
                           fill=self.accent, font=("Segoe UI", 8, "bold"))

        if time.monotonic() - self._last_activity > 120:
            self.fade()

        if self._fade_started is not None:
            opacity = max(0.0, 1.0 - (time.monotonic() - self._fade_started) / 0.42)
            try:
                self.attributes("-alpha", opacity)
            except tk.TclError:
                pass
            if opacity <= 0:
                self.hide()
                return
        self._animation_handle = self.after(40, self._animate)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._animation_handle is not None:
            try:
                self.after_cancel(self._animation_handle)
            except tk.TclError:
                pass
            self._animation_handle = None
        try:
            self.destroy()
        except tk.TclError:
            pass
