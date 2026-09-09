"""A shared, main-thread-only desktop interface for FRIDAY and Alfred.

The controller owns all audio, network and operating-system work. This module
only submits requests and consumes its event queue; importing it opens no window.
"""

from __future__ import annotations

import math
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from .tray import SystemTray, WakeOverlay

try:
    import psutil
except ImportError:  # The UI still opens so dependency diagnostics are reachable.
    psutil = None


BG = "#080D13"
PANEL = "#0E1721"
INSET = "#0A111A"
LINE = "#223140"
TEXT = "#E8F1F7"
MUTED = "#8DA3B5"
ERROR = "#FF8E85"
FONT = "Segoe UI"
MONO = "Consolas"


class AssistantWindow(ctk.CTk):
    """Render a controller without accessing Tk from its worker threads."""

    def __init__(self, controller, background=False):
        ctk.set_appearance_mode("dark")
        super().__init__()
        if background:
            self.withdraw()
        self.controller = controller
        self.persona = controller.settings.persona
        self.name = controller.settings.display_name
        supplied_accent = getattr(controller.settings, "accent", "")
        self.accent = supplied_accent if re.fullmatch(r"#[0-9a-fA-F]{6}", supplied_accent or "") else (
            "#D9B65E" if self.persona == "alfred" else "#4ADCEB"
        )
        self.dim_accent = self._mix(self.accent, PANEL, 0.24)
        self._closed = False
        self._hidden_to_tray = False
        self._wake_overlay_session = False
        self._tray_notice_shown = False
        self._scheduled: set[str] = set()
        self._state = "standby"
        self._phase = 0.0
        self._dialog = None
        self._message_count = 0
        self._started_at = time.monotonic()
        self._wake = tk.BooleanVar(
            master=self, value=bool(getattr(controller.settings, "wake_on_start", False))
        )
        self._speech = tk.BooleanVar(master=self, value=bool(controller.settings.speech_enabled))
        self._tray = SystemTray(self.name, self.accent, self.persona)
        self._overlay = None

        self.title(f"{self.name} · Personal assistant")
        width = min(1120, max(880, self.winfo_screenwidth() - 80))
        height = min(780, max(640, self.winfo_screenheight() - 100))
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        self.geometry(f"{width}x{height}+{x}+20")
        self.minsize(880, 640)
        self.configure(fg_color=BG)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.bind("<Unmap>", self._on_unmap, add="+")
        self.bind("<Escape>", self._stop)
        self.bind("<Control-q>", lambda _event: self._exit())
        self.bind("<Control-l>", lambda _event: self.composer.focus_set())

        self._build_header()
        self._build_workspace()
        self._build_footer()
        self._overlay = WakeOverlay(self, self.accent, self.name)
        self._tray.set_state(
            speech_enabled=self._speech.get(), wake_enabled=self._wake.get()
        )
        self._tray.start()
        wake_intro = (
            f'Wake listening is enabled; say "{self.persona}" when you need me.'
            if self._wake.get() else "Wake listening is off until you enable it."
        )
        self._append_message("system", (
            f"Welcome. Type a message or press Talk to {self.name}. "
            "Local PC commands work without an AI key. Add a Groq API key in Settings "
            f"for open-ended conversation. {wake_intro}"
        ))
        self._refresh_config()
        self._schedule(60, self._poll_events)
        self._schedule(50, self._animate)
        self._schedule(200, self._update_telemetry)
        self._schedule(100, self._poll_tray)
        if background:
            self._hide_to_tray()
        else:
            self._schedule(300, self.composer.focus_set)

    @staticmethod
    def _mix(first, second, amount):
        a = tuple(int(first[i:i + 2], 16) for i in (1, 3, 5))
        b = tuple(int(second[i:i + 2], 16) for i in (1, 3, 5))
        return "#" + "".join(f"{round(x * amount + y * (1 - amount)):02x}" for x, y in zip(a, b))

    def _schedule(self, milliseconds, callback):
        if self._closed:
            return
        handle = None

        def run():
            self._scheduled.discard(handle)
            if not self._closed:
                callback()

        handle = self.after(milliseconds, run)
        self._scheduled.add(handle)

    def _label(self, master, text, *, size=12, color=MUTED, bold=False, **kwargs):
        kwargs.setdefault("height", 0)
        return ctk.CTkLabel(master, text=text, text_color=color,
                            font=(FONT, size, "bold" if bold else "normal"), **kwargs)

    def _button(self, master, text, command, *, primary=False, **kwargs):
        return ctk.CTkButton(
            master, text=text, command=command, height=36, corner_radius=8,
            fg_color=self.accent if primary else "#172432",
            hover_color=self._mix(self.accent, "#FFFFFF", 0.78) if primary else "#253749",
            text_color=BG if primary else TEXT, font=(FONT, 12, "bold"), **kwargs
        )

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(17, 13))
        header.grid_columnconfigure(1, weight=1)
        mark = ctk.CTkFrame(header, width=4, height=46, fg_color=self.accent, corner_radius=2)
        mark.grid(row=0, column=0, rowspan=2, padx=(0, 13), sticky="ns")
        self._label(header, self.name, size=27, color=TEXT, bold=True, anchor="w").grid(
            row=0, column=1, sticky="w")
        identity = "WAYNE MANOR / PERSONAL ASSISTANT" if self.persona == "alfred" else "PERSONAL INTELLIGENCE / DESKTOP ASSISTANT"
        self._label(header, identity, size=10, anchor="w").grid(row=1, column=1, sticky="w")
        self._button(header, "Hide to tray", self._hide_to_tray, width=96).grid(
            row=0, column=2, rowspan=2, padx=6
        )
        self._button(header, "Diagnostics", self._diagnostics, width=98).grid(
            row=0, column=3, rowspan=2, padx=6
        )
        self._button(header, "Settings", self._open_settings, width=86).grid(
            row=0, column=4, rowspan=2, padx=(6, 0)
        )

    def _build_workspace(self):
        workspace = ctk.CTkFrame(self, fg_color="transparent")
        workspace.grid(row=1, column=0, sticky="nsew", padx=22)
        workspace.grid_rowconfigure(0, weight=1)
        workspace.grid_columnconfigure(1, weight=1)
        self._build_sidebar(workspace)
        self._build_conversation(workspace)

    def _build_sidebar(self, workspace):
        sidebar = ctk.CTkFrame(workspace, width=238, fg_color=PANEL, corner_radius=14,
                               border_color=LINE, border_width=1)
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(4, weight=1)
        self._label(sidebar, "ASSISTANT STATE", size=10, bold=True).grid(row=0, column=0, pady=(18, 0))
        self.core_canvas = tk.Canvas(sidebar, width=216, height=181, bg=PANEL, highlightthickness=0)
        self.core_canvas.grid(row=1, column=0, padx=10)
        self.state_label = self._label(sidebar, "STANDBY", size=17, color=self.accent, bold=True)
        self.state_label.grid(row=2, column=0, padx=16, pady=(0, 2))
        self.detail_label = self._label(sidebar, "Ready for a message.", size=11, wraplength=198, justify="center")
        self.detail_label.grid(row=3, column=0, padx=16, pady=(0, 12))

        controls = ctk.CTkFrame(sidebar, fg_color="transparent")
        controls.grid(row=5, column=0, sticky="ew", padx=17, pady=(0, 15))
        controls.grid_columnconfigure(0, weight=1)
        ctk.CTkFrame(controls, height=1, fg_color=LINE).grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.speech_switch = ctk.CTkSwitch(controls, text="Spoken replies", variable=self._speech,
            command=self._toggle_speech, progress_color=self.accent, button_color=TEXT,
            font=(FONT, 12), text_color=TEXT, switch_width=34, switch_height=18)
        self.speech_switch.grid(row=1, column=0, sticky="w", pady=(0, 12))
        self.wake_switch = ctk.CTkSwitch(controls, text=f'Wake word: "{self.persona}"', variable=self._wake,
            command=self._toggle_wake, progress_color=self.accent, button_color=TEXT,
            font=(FONT, 12), text_color=TEXT, switch_width=34, switch_height=18)
        self.wake_switch.grid(row=2, column=0, sticky="w")
        self._label(controls, "Local wake detection. Your requests\nuse online speech recognition.",
                    size=10, justify="left", anchor="w").grid(row=3, column=0, sticky="w", pady=(7, 12))
        self._label(controls, "THIS PC · LIVE", size=10, bold=True, anchor="w").grid(row=4, column=0, sticky="w", pady=(0, 7))
        self.cpu_label = self._label(controls, "CPU   —", size=11, anchor="w")
        self.cpu_label.grid(row=5, column=0, sticky="ew")
        self.cpu_bar = ctk.CTkProgressBar(controls, height=4, fg_color=LINE, progress_color=self.accent)
        self.cpu_bar.set(0)
        self.cpu_bar.grid(row=6, column=0, sticky="ew", pady=(2, 7))
        self.memory_label = self._label(controls, "Memory   —", size=11, anchor="w")
        self.memory_label.grid(row=7, column=0, sticky="ew")
        self.memory_bar = ctk.CTkProgressBar(controls, height=4, fg_color=LINE, progress_color=self.accent)
        self.memory_bar.set(0)
        self.memory_bar.grid(row=8, column=0, sticky="ew", pady=(2, 0))

    def _build_conversation(self, workspace):
        conversation = ctk.CTkFrame(workspace, fg_color=PANEL, border_width=1, border_color=LINE, corner_radius=14)
        conversation.grid(row=0, column=1, sticky="nsew")
        conversation.grid_columnconfigure(0, weight=1)
        conversation.grid_rowconfigure(1, weight=1)
        titlebar = ctk.CTkFrame(conversation, fg_color="transparent")
        titlebar.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 11))
        titlebar.grid_columnconfigure(0, weight=1)
        self._label(titlebar, "Conversation", size=17, color=TEXT, bold=True).grid(row=0, column=0, sticky="w")
        self.session_label = self._label(titlebar, "THIS SESSION", size=10)
        self.session_label.grid(row=0, column=1, padx=10)
        self._button(titlebar, "Clear", self._clear_conversation, width=54).grid(row=0, column=2)

        transcript_frame = ctk.CTkFrame(conversation, fg_color=INSET, corner_radius=9)
        transcript_frame.grid(row=1, column=0, sticky="nsew", padx=15)
        transcript_frame.grid_columnconfigure(0, weight=1)
        transcript_frame.grid_rowconfigure(0, weight=1)
        self.transcript = tk.Text(transcript_frame, wrap="word", state="disabled", borderwidth=0,
            highlightthickness=0, bg=INSET, fg=TEXT, font=(FONT, 12), padx=17, pady=15,
            insertbackground=self.accent, selectbackground="#2E5268", selectforeground="#FFFFFF",
            spacing1=2, spacing3=6, cursor="arrow", width=35, height=8)
        self.transcript.grid(row=0, column=0, sticky="nsew", padx=(3, 0), pady=3)
        scrollbar = ctk.CTkScrollbar(transcript_frame, command=self.transcript.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 3), pady=6)
        self.transcript.configure(yscrollcommand=scrollbar.set)
        for role, color in (("assistant", self.accent), ("user", TEXT), ("system", MUTED), ("error", ERROR)):
            self.transcript.tag_configure(f"heading_{role}", foreground=color, font=(MONO, 10, "bold"), spacing1=10, spacing3=5)
        self.transcript.tag_configure("body", foreground=TEXT, spacing3=14)
        self.transcript.tag_configure("system_body", foreground=MUTED, spacing3=14)
        self.transcript.tag_configure("error_body", foreground=ERROR, spacing3=14)
        self.transcript.bind("<Control-a>", self._select_transcript)

        suggestions = ctk.CTkFrame(conversation, fg_color="transparent")
        suggestions.grid(row=2, column=0, sticky="ew", padx=15, pady=(10, 9))
        for index, (title, prompt) in enumerate((
                ("What can you do?", "What can you do?"),
                ("Open Notepad", "Open Notepad"),
                ("System status", "System status"))):
            suggestions.grid_columnconfigure(index, weight=1)
            button = ctk.CTkButton(suggestions, text=title, command=lambda p=prompt: self._send_suggestion(p),
                height=29, corner_radius=7, fg_color="transparent", border_width=1, border_color=LINE,
                hover_color="#1D2D3D", text_color=MUTED, font=(FONT, 11), width=80)
            button.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 5, 0))

        composer_frame = ctk.CTkFrame(conversation, fg_color=INSET, corner_radius=10, border_width=1, border_color=LINE)
        composer_frame.grid(row=3, column=0, sticky="ew", padx=15)
        composer_frame.grid_columnconfigure(0, weight=1)
        self.composer = ctk.CTkTextbox(composer_frame, height=68, wrap="word", fg_color="transparent",
            text_color=TEXT, font=(FONT, 13), border_width=0, corner_radius=6, scrollbar_button_color=LINE)
        self.composer.grid(row=0, column=0, sticky="ew", padx=6, pady=5)
        self.composer.bind("<Return>", self._composer_return)
        self.composer.bind("<Shift-Return>", self._composer_newline)
        self._button(composer_frame, "Send  ↗", self._send, primary=True, width=86).grid(row=0, column=1, padx=(6, 12))

        actions = ctk.CTkFrame(conversation, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="ew", padx=15, pady=(10, 14))
        actions.grid_columnconfigure(2, weight=1)
        self.talk_button = self._button(actions, f"Talk to {self.name}", self._listen, width=145)
        self.talk_button.grid(row=0, column=0, sticky="w")
        self._button(actions, "Stop · Esc", self._stop, width=85).grid(row=0, column=1, padx=(7, 0))
        self._label(actions, "Enter to send  ·  Shift + Enter for a new line", size=10, anchor="e").grid(row=0, column=2, sticky="e", padx=(8, 0))

    def _build_footer(self):
        footer = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        footer.grid(row=2, column=0, sticky="ew", padx=24, pady=(9, 10))
        footer.grid_columnconfigure(0, weight=1)
        self.connection_label = self._label(footer, "", size=10, anchor="w")
        self.connection_label.grid(row=0, column=0, sticky="w")
        self.clock_label = self._label(footer, "", size=10, anchor="e")
        self.clock_label.grid(row=0, column=1, sticky="e")

    def _select_transcript(self, _event):
        self.transcript.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _append_message(self, role, text):
        if not text:
            return
        role = role if role in {"assistant", "user", "system", "error"} else "system"
        label = {"assistant": self.name, "user": "YOU", "system": "SYSTEM", "error": "ATTENTION"}[role]
        bottom = self.transcript.yview()[1] >= 0.96
        self.transcript.configure(state="normal")
        self.transcript.insert("end", f"{label}  ·  {time.strftime('%H:%M')}\n", f"heading_{role}")
        body_style = "system_body" if role == "system" else "error_body" if role == "error" else "body"
        self.transcript.insert("end", str(text).strip() + "\n\n", body_style)
        self.transcript.configure(state="disabled")
        if bottom or role == "user":
            self.transcript.see("end")
        if role in {"assistant", "user"}:
            self._message_count += 1
            self.session_label.configure(text=f"{self._message_count} MESSAGES")

    def _poll_events(self):
        # Bound each batch so a chatty worker cannot monopolize the Tk event loop.
        for _ in range(100):
            try:
                event = self.controller.events.get_nowait()
            except queue.Empty:
                break
            if not isinstance(event, dict):
                continue
            kind = event.get("kind")
            if kind == "message":
                self._append_message(event.get("role", "system"), event.get("text", ""))
            elif kind == "status":
                self._set_status(event.get("state", "standby"), event.get("detail", ""))
            elif kind in {"notice", "error"}:
                self._append_message("error" if kind == "error" else "system", event.get("message") or event.get("text", ""))
            elif kind in {"config", "settings"}:
                self._refresh_config()
            elif kind == "wake":
                self._wake.set(bool(event.get("enabled", False)))
                self._tray.set_state(wake_enabled=self._wake.get())
            elif kind == "wake_detected":
                self._wake_overlay_session = True
                self._overlay.show("listening", event.get("detail", "Listening"))
        self._schedule(60, self._poll_events)

    def _poll_tray(self):
        """Run native tray requests on Tk's owning thread."""
        for _ in range(20):
            try:
                command = self._tray.get_nowait()
            except queue.Empty:
                break
            if command == "show":
                self._show_window()
            elif command == "toggle_speech":
                self._speech.set(not self._speech.get())
                self._toggle_speech()
            elif command == "toggle_wake":
                self._wake.set(not self._wake.get())
                self._toggle_wake()
            elif command == "exit":
                self._exit()
                return
        self._schedule(100, self._poll_tray)

    def _set_status(self, state, detail):
        previous = self._state
        self._state = str(state).lower()
        color = ERROR if self._state == "error" else self.accent
        self.state_label.configure(text=str(state).upper(), text_color=color)
        self.detail_label.configure(text=detail or {
            "ready": "Ready for your next request.", "standby": "Ready for a message.",
            "listening": "Listening to your microphone…", "transcribing": "Turning speech into text…",
            "thinking": "Working on your request…", "speaking": "Speaking. Press Esc to interrupt.",
            "error": "See the conversation for details.",
        }.get(self._state, ""))
        busy = self._state in {"listening", "transcribing", "thinking", "speaking"}
        self.talk_button.configure(state="disabled" if busy else "normal")
        # Newer voice services emit wake_detected.  The transition fallback also
        # keeps the overlay useful with an older controller during an upgrade.
        if self._wake_overlay_session and self._state in {
                "listening", "transcribing", "thinking", "speaking"}:
            self._overlay.set_phase(self._state, detail)
        elif self._wake_overlay_session and self._state in {"ready", "standby", "error"}:
            self._overlay.fade()
            self._wake_overlay_session = False

    def _composer_return(self, event):
        if event.state & 0x0001:
            return self._composer_newline(event)
        self._send()
        return "break"

    def _composer_newline(self, _event):
        self.composer.insert("insert", "\n")
        return "break"

    def _send(self):
        text = self.composer.get("1.0", "end-1c").strip()
        if text:
            try:
                self.controller.submit(text)
            except Exception as exc:
                self._append_message("error", str(exc))
                return
            self.composer.delete("1.0", "end")
            self.composer.focus_set()

    def _send_suggestion(self, prompt):
        self.composer.delete("1.0", "end")
        self.composer.insert("1.0", prompt)
        self._send()

    def _listen(self):
        try:
            self.controller.listen_once()
        except Exception as exc:
            self._append_message("error", str(exc))

    def _stop(self, _event=None):
        self.controller.stop()
        return "break"

    def _toggle_wake(self):
        try:
            self.controller.set_wake_enabled(self._wake.get())
            self._tray.set_state(wake_enabled=self._wake.get())
        except Exception as exc:
            self._wake.set(False)
            self._tray.set_state(wake_enabled=False)
            self._append_message("error", str(exc))

    def _toggle_speech(self):
        try:
            self.controller.save_settings({"speech_enabled": self._speech.get()})
            self._refresh_config()
        except Exception as exc:
            self._speech.set(bool(self.controller.settings.speech_enabled))
            self._tray.set_state(speech_enabled=self._speech.get())
            self._append_message("error", str(exc))

    def _diagnostics(self):
        try:
            self.controller.diagnostics()
        except Exception as exc:
            self._append_message("error", str(exc))

    def _clear_conversation(self):
        self.controller.clear_conversation()
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")
        self._message_count = 0
        self.session_label.configure(text="THIS SESSION")
        self._append_message("system", "Conversation cleared. Saved memories are managed in Settings.")

    def _refresh_config(self):
        settings = self.controller.settings
        self._speech.set(bool(settings.speech_enabled))
        self._tray.set_state(speech_enabled=self._speech.get(), wake_enabled=self._wake.get())
        configured = bool(getattr(settings, "api_key", ""))
        model = getattr(settings, "model", "")
        conversation = f"Groq configured · {model}" if configured else "Local commands available · Add an AI key in Settings"
        stt = {"auto": "Auto (Groq / Google)", "groq": "Groq", "google": "Google"}.get(getattr(settings, "stt_provider", "auto"), "Auto")
        self.connection_label.configure(text=f"{conversation}    /    Speech recognition: {stt}")

    def _update_telemetry(self):
        if self._hidden_to_tray:
            self._schedule(5000, self._update_telemetry)
            return
        if psutil is not None:
            try:
                cpu = psutil.cpu_percent(interval=None)
                memory = psutil.virtual_memory()
                self.cpu_label.configure(text=f"CPU   {cpu:.0f}%")
                self.cpu_bar.set(cpu / 100)
                self.memory_label.configure(text=f"Memory   {memory.percent:.0f}% · {memory.used / 1024 ** 3:.1f} GB")
                self.memory_bar.set(memory.percent / 100)
            except (OSError, RuntimeError):
                self.cpu_label.configure(text="CPU   unavailable")
                self.memory_label.configure(text="Memory   unavailable")
        else:
            self.cpu_label.configure(text="CPU   install psutil")
            self.memory_label.configure(text="Memory   install psutil")
        self.clock_label.configure(text=time.strftime("%a %d %b  ·  %H:%M:%S"))
        self._schedule(1200, self._update_telemetry)

    def _animate(self):
        if self._hidden_to_tray:
            # The small wake overlay has its own animation. Do no drawing for
            # the invisible main window while the assistant is in the tray.
            self._schedule(300, self._animate)
            return
        self._phase += 0.035 if self._state in {"standby", "ready"} else 0.10
        canvas = self.core_canvas
        canvas.delete("all")
        cx, cy = 108, 89
        color = ERROR if self._state == "error" else self.accent
        active = self._state in {"listening", "thinking", "transcribing", "speaking"}
        pulse = (math.sin(self._phase * 2) + 1) / 2
        for radius in (86, 72):
            canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                               outline=self.dim_accent, width=1)
        for tick in range(48):
            angle = math.radians(tick * 7.5)
            inner = 82 if tick % 4 else 78
            canvas.create_line(cx + inner * math.cos(angle), cy + inner * math.sin(angle),
                cx + 86 * math.cos(angle), cy + 86 * math.sin(angle),
                fill=self.dim_accent if tick % 4 else color, width=1)
        rotation = math.degrees(self._phase) % 360
        for offset in (0, 120, 240):
            canvas.create_arc(cx - 73, cy - 73, cx + 73, cy + 73, start=rotation + offset,
                              extent=43, style="arc", outline=color, width=2)
        if self.persona == "alfred":
            self._draw_bat(canvas, cx, cy, color, pulse, active)
        else:
            self._draw_reactor(canvas, cx, cy, color, pulse, active)
        self._schedule(250 if self._hidden_to_tray else 50, self._animate)

    def _draw_reactor(self, canvas, cx, cy, color, pulse, active):
        for radius, opacity in ((63, 0.08), (57, 0.13), (50, 0.21)):
            canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                fill=self._mix(color, PANEL, opacity + pulse * (0.06 if active else 0.02)), outline="")
        for index in range(8):
            angle = math.radians(index * 45 + 22.5)
            points = []
            for radius, delta in ((63, -0.075), (63, 0.075), (46, 0.10), (46, -0.10)):
                points.extend((cx + radius * math.cos(angle + delta), cy + radius * math.sin(angle + delta)))
            canvas.create_polygon(points, fill=self._mix(color, PANEL, 0.75), outline="")
        radius = 35 + pulse * (3 if active else 1)
        canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
            fill=self._mix(color, PANEL, 0.10), outline=color, width=2)
        triangle = []
        for degrees in (90, 210, 330):
            angle = math.radians(degrees)
            triangle.extend((cx + 25 * math.cos(angle), cy + 25 * math.sin(angle)))
        canvas.create_polygon(triangle, fill=self._mix(color, PANEL, 0.14), outline=color, width=2)
        canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill=TEXT, outline="")

    def _draw_bat(self, canvas, cx, cy, color, pulse, active):
        canvas.create_oval(cx - 68, cy - 42, cx + 68, cy + 42,
            outline=self._mix(color, PANEL, 0.4 + pulse * 0.12), width=1,
            fill=self._mix(color, PANEL, 0.045))
        # Symmetric angular wings, pointed ears and a scalloped lower silhouette.
        contour = [(-68, -25), (-49, -17), (-30, -20), (-16, -6), (-10, -10),
            (-8, -29), (-3, -19), (3, -19), (8, -29), (10, -10), (16, -6),
            (30, -20), (49, -17), (68, -25), (58, -4), (49, 0), (48, 10),
            (37, 7), (28, 12), (26, 21), (16, 16), (8, 23), (0, 36),
            (-8, 23), (-16, 16), (-26, 21), (-28, 12), (-37, 7), (-48, 10),
            (-49, 0), (-58, -4)]
        canvas.create_polygon([value for x, y in contour for value in (cx + x, cy + y)],
            fill=self._mix(color, PANEL, 0.68 + pulse * (0.22 if active else 0.08)), outline=color, width=1)
        for x in (-73, 73):
            canvas.create_line(cx + x, cy - 9, cx + x, cy + 9, fill=color, width=2)

    def _open_settings(self):
        if self._dialog is not None and self._dialog.winfo_exists():
            self._dialog.lift()
            self._dialog.focus_set()
            return
        self._dialog = SettingsDialog(self)

    def _hide_to_tray(self):
        if self._closed:
            return
        if self._tray.available:
            self._hidden_to_tray = True
            self.withdraw()
            return
        # Keep a taskbar route back to the assistant when the optional tray
        # integration is unavailable.
        self._hidden_to_tray = False
        self.iconify()
        if not self._tray_notice_shown:
            self._tray_notice_shown = True
            self._append_message(
                "system", "The system tray integration is unavailable, so the window was minimized instead."
            )

    def _show_window(self):
        if self._closed:
            return
        self._hidden_to_tray = False
        self.deiconify()
        try:
            self.state("normal")
        except tk.TclError:
            pass
        self.lift()
        self._schedule(60, self.composer.focus_set)

    def _on_destroy(self, event):
        if event.widget is self:
            self._tray.stop()

    def _on_unmap(self, event):
        if (event.widget is self and not self._closed and self._tray.available
                and self.state() == "iconic"):
            self._schedule(0, self._hide_to_tray)

    def _close(self):
        """Compatibility alias for callers that explicitly mean full exit."""
        self._exit()

    def _exit(self):
        if self._closed:
            return
        self._closed = True
        self._tray.stop()
        if self._overlay is not None:
            self._overlay.close()
        for handle in tuple(self._scheduled):
            try:
                self.after_cancel(handle)
            except tk.TclError:
                pass
        self._scheduled.clear()
        # CustomTkinter also owns delayed title-bar, focus and scaling callbacks.
        # Cancel them before destroying their registered Tcl commands.
        for handle in self.tk.call("after", "info"):
            try:
                # Leave command disposal to the widget that registered it.
                self.tk.call("after", "cancel", handle)
            except tk.TclError:
                pass
        try:
            self.controller.close()
        finally:
            self.destroy()


class SettingsDialog(ctk.CTkToplevel):
    """Scrollable configuration; no microphone enumeration on the Tk thread."""

    VOICES = ("en-US-EmmaMultilingualNeural", "en-IE-EmilyNeural", "en-GB-SoniaNeural", "en-GB-RyanNeural", "en-GB-ThomasNeural",
              "en-US-JennyNeural", "en-US-GuyNeural", "en-IN-NeerjaNeural", "en-IN-PrabhatNeural")
    GROQ_VOICES = ("autumn", "diana", "hannah", "austin", "daniel", "troy")

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.controller = parent.controller
        settings = self.controller.settings
        self.title(f"{parent.name} · Settings")
        self.configure(fg_color=BG)
        screen_height = self.winfo_screenheight()
        self.geometry(f"650x{min(735, screen_height - 85)}")
        self.minsize(540, 480)
        self.transient(parent)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._mic_queue = queue.Queue()
        self._mic_values = {"System default": None}
        self._mic_value = "System default"
        if settings.microphone_index is not None:
            self._mic_value = f"Device {settings.microphone_index} (saved)"
            self._mic_values[self._mic_value] = settings.microphone_index

        parent._label(self, "Make it yours", size=23, bold=True, color=TEXT, anchor="w").grid(
            row=0, column=0, sticky="w", padx=24, pady=(19, 12))
        content = ctk.CTkScrollableFrame(self, fg_color=PANEL, corner_radius=12)
        content.grid(row=1, column=0, sticky="nsew", padx=20)
        content.grid_columnconfigure(0, weight=1)
        self._content = content
        self._row = 0
        self._section("STARTUP")
        self.start_with_windows = tk.BooleanVar(master=self, value=settings.start_with_windows)
        ctk.CTkSwitch(content, text="Start with Windows", variable=self.start_with_windows,
                      progress_color=parent.accent, text_color=TEXT, font=(FONT, 12)).grid(
            row=self._row, column=0, sticky="w", padx=14, pady=(4, 10))
        self._row += 1
        self._hint("Start quietly in the tray when you sign in. Switch off and Save to disable.\n"
                   "Enable Wake word in the main window to listen after startup.\n"
                   "If disabled in Windows Startup Apps, enable it there too.")
        self._section("CONVERSATION")
        self.api_key = self._entry("Groq API key", getattr(settings, "api_key", ""), show="•")
        self._hint("Used for natural conversation and, if selected, Groq speech recognition.\nThe key is hidden here; it is never included in diagnostic output.")
        self.model = self._combo("Conversation model", settings.model, ("auto", "openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"))
        self._hint("Use auto to select an available model, or enter a model your Groq account supports.")
        self._section("VOICE & MICROPHONE")
        self.voice_provider = self._combo(
            "Voice quality", getattr(settings, "voice_provider", "edge"),
            ("groq", "edge"), readonly=True,
        )
        self._hint(
            "Groq — optional high quality, expressive speech; your Groq account must accept the model terms.\n"
            "Edge — standard neural speech and the Windows voice fallback."
        )
        default_groq_voice = "daniel" if settings.persona == "alfred" else "diana"
        self.groq_voice = self._combo(
            "Expressive Groq voice", getattr(settings, "groq_voice", default_groq_voice),
            self.GROQ_VOICES, readonly=True,
        )
        self.voice = self._combo("Edge speaking voice", settings.voice, self.VOICES)
        self._hint("FRIDAY: Emma for natural delivery, or Emily for an Irish accent.\nAlfred: en-GB-RyanNeural. Windows speech is the offline fallback.")
        parent._button(content, "Test saved voice", self._test_voice, width=150).grid(
            row=self._row, column=0, sticky="w", padx=14, pady=(0, 9))
        self._row += 1
        self.stt = self._combo("Speech recognition service", settings.stt_provider, ("auto", "groq", "google"), readonly=True)
        self.language = self._entry("Recognition language", settings.recognition_language)
        self._hint("Auto uses Groq Whisper with Google fallback. Examples: en-IN, en-GB, hi-IN.\nThe local wake detector listens for your assistant's name. Requests use online recognition.")
        self.microphone = self._combo("Microphone", self._mic_value, tuple(self._mic_values), readonly=True)
        mic_actions = ctk.CTkFrame(content, fg_color="transparent")
        mic_actions.grid(row=self._row, column=0, sticky="ew", padx=14, pady=(0, 10))
        self._row += 1
        self.mic_status = parent._label(mic_actions, "Loading input devices…", size=10, anchor="w", wraplength=365)
        self.mic_status.pack(side="left", fill="x", expand=True)
        self.refresh_mics = parent._button(mic_actions, "Refresh", self._load_microphones, width=74)
        self.refresh_mics.pack(side="right")
        self.followup = self._entry("Follow-up listening (seconds)", str(settings.followup_seconds))
        self._hint("After a voice reply, keep listening for this long. Use 0 to turn follow-ups off.")
        self._section("SAVED MEMORIES")
        self._hint("Clear facts you have asked the assistant to remember. This cannot be undone.")
        parent._button(content, "Clear saved memories", self._clear_memories, width=180).grid(
            row=self._row, column=0, sticky="w", padx=14, pady=(0, 18))
        self._row += 1

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=23, pady=16)
        bottom.grid_columnconfigure(0, weight=1)
        self.error_label = parent._label(bottom, "", color=ERROR, size=11, wraplength=365, justify="left", anchor="w")
        self.error_label.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        parent._button(bottom, "Cancel", self.destroy, width=72).grid(row=0, column=1, padx=(0, 8))
        parent._button(bottom, "Save", self._save, primary=True, width=80).grid(row=0, column=2)
        self.bind("<Escape>", lambda _event: self.destroy())
        self._load_microphones()
        parent._schedule(100, self._poll_microphones)
        parent._schedule(150, lambda: self.lift() if self.winfo_exists() else None)

    def _section(self, text):
        self.parent._label(self._content, text, size=10, color=self.parent.accent, bold=True, anchor="w").grid(
            row=self._row, column=0, sticky="ew", padx=14, pady=(16, 9))
        self._row += 1

    def destroy(self):
        commands = set(self._tclCommands or ())
        for handle in self.tk.call("after", "info"):
            try:
                script = str(self.tk.call("after", "info", handle)[0])
                if script.split(" ", 1)[0] in commands:
                    self.after_cancel(handle)
            except tk.TclError:
                pass
        super().destroy()

    def _field_label(self, label):
        self.parent._label(self._content, label, size=12, color=TEXT, anchor="w").grid(
            row=self._row, column=0, sticky="ew", padx=14, pady=(5, 4))
        self._row += 1

    def _entry(self, label, value, **kwargs):
        self._field_label(label)
        field = ctk.CTkEntry(self._content, height=36, fg_color=INSET, border_color=LINE,
                            text_color=TEXT, font=(FONT, 12), **kwargs)
        field.insert(0, str(value or ""))
        field.grid(row=self._row, column=0, sticky="ew", padx=14, pady=(0, 7))
        self._row += 1
        return field

    def _combo(self, label, value, options, readonly=False):
        self._field_label(label)
        values = list(options)
        if value and value not in values:
            values.insert(0, value)
        field = ctk.CTkComboBox(self._content, values=values, height=36, fg_color=INSET,
            border_color=LINE, button_color=LINE, button_hover_color="#35495A", text_color=TEXT,
            dropdown_fg_color=PANEL, dropdown_text_color=TEXT, dropdown_hover_color="#26394C",
            font=(FONT, 12), state="readonly" if readonly else "normal")
        field.set(str(value or values[0]))
        field.grid(row=self._row, column=0, sticky="ew", padx=14, pady=(0, 7))
        self._row += 1
        return field

    def _hint(self, text):
        self.parent._label(self._content, text, size=10, justify="left", anchor="w", wraplength=490).grid(
            row=self._row, column=0, sticky="ew", padx=14, pady=(0, 8))
        self._row += 1

    def _load_microphones(self):
        self.refresh_mics.configure(state="disabled")
        self.mic_status.configure(text="Loading input devices…")

        def discover():
            try:
                self._mic_queue.put((True, self.controller.list_microphones()))
            except Exception as exc:
                self._mic_queue.put((False, str(exc)))

        threading.Thread(target=discover, name="assistant-ui-microphones", daemon=True).start()

    def _poll_microphones(self):
        if not self.winfo_exists():
            return
        try:
            ok, result = self._mic_queue.get_nowait()
        except queue.Empty:
            self.parent._schedule(100, self._poll_microphones)
            return
        self.refresh_mics.configure(state="normal")
        if ok:
            selected_index = self._mic_values.get(self.microphone.get())
            self._mic_values = {"System default": None}
            selected = "System default"
            for index, name in result:
                label = f"{index} · {name}"
                self._mic_values[label] = index
                if index == selected_index:
                    selected = label
            if selected_index is not None and selected == "System default":
                selected = f"Device {selected_index} (not currently detected)"
                self._mic_values[selected] = selected_index
            self.microphone.configure(values=list(self._mic_values))
            self.microphone.set(selected)
            self.mic_status.configure(text=f"{len(result)} input devices found." if result else "No input devices detected. Check Windows microphone access.")
        else:
            self.mic_status.configure(text=f"Input discovery: {result}")
        self.parent._schedule(100, self._poll_microphones)

    def _clear_memories(self):
        if messagebox.askyesno("Clear saved memories?", "Permanently remove facts saved by this assistant?", parent=self):
            try:
                self.controller.clear_memories()
                self.error_label.configure(text="Saved memories cleared.", text_color=MUTED)
            except Exception as exc:
                self.error_label.configure(text=str(exc), text_color=ERROR)

    def _test_voice(self):
        try:
            self.controller.test_voice()
            self.error_label.configure(text="Testing your saved voice settings.", text_color=MUTED)
        except Exception as exc:
            self.error_label.configure(text=str(exc), text_color=ERROR)

    def _save(self):
        try:
            try:
                followup = int(self.followup.get().strip())
            except ValueError:
                raise ValueError("Follow-up seconds must be a whole number between 0 and 60.") from None
            if not 0 <= followup <= 60:
                raise ValueError("Follow-up seconds must be between 0 and 60.")
            values = {
                "api_key": self.api_key.get().strip(), "model": self.model.get().strip(),
                "voice_provider": self.voice_provider.get(),
                "groq_voice": self.groq_voice.get(),
                "voice": self.voice.get().strip(), "stt_provider": self.stt.get(),
                "recognition_language": self.language.get().strip(),
                "microphone_index": self._mic_values.get(self.microphone.get()),
                "followup_seconds": followup,
                "start_with_windows": self.start_with_windows.get(),
            }
            self.controller.save_settings(values)
        except (ValueError, OSError) as exc:
            self.error_label.configure(text=str(exc), text_color=ERROR)
            return
        self.parent._refresh_config()
        self.parent._append_message("system", "Settings saved.")
        self.destroy()
