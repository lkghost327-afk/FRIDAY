"""A shared, main-thread-only desktop interface for FRIDAY and Alfred.

The controller owns all audio, network and operating-system work. This module
only submits requests and consumes its event queue; importing it opens no window.
"""

from __future__ import annotations

import math
import queue
import os
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
        self._message_serial = 0
        self._compact = True
        self._last_request = ""
        self._shortcut_finish = None
        self._started_at = time.monotonic()
        self._wake = tk.BooleanVar(
            master=self, value=bool(getattr(controller.settings, "wake_on_start", False))
        )
        self._speech = tk.BooleanVar(master=self, value=bool(controller.settings.speech_enabled))
        self._tray = SystemTray(self.name, self.accent, self.persona)
        self._overlay = None

        self.title(f"{self.name} · Personal assistant")
        width = min(740, self.winfo_screenwidth() - 40)
        height = min(620, self.winfo_screenheight() - 80)
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        self.geometry(f"{width}x{height}+{x}+20")
        self.minsize(660, 510)
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
        self._label(header, self.name, size=22, color=TEXT, bold=True, anchor="w").grid(
            row=0, column=1, sticky="w")
        identity = "Your desktop, one request away"
        self._label(header, identity, size=10, anchor="w").grid(row=1, column=1, sticky="w")
        self.layout_button = self._button(header, "Expand", self._toggle_layout, width=66)
        self.layout_button.grid(row=0, column=5, rowspan=2, padx=(6, 0))
        self._button(header, "Hide", self._hide_to_tray, width=55).grid(
            row=0, column=2, rowspan=2, padx=6
        )
        self._button(header, "Check", self._diagnostics, width=58).grid(
            row=0, column=3, rowspan=2, padx=6
        )
        self._button(header, "Settings", self._open_settings, width=86).grid(
            row=0, column=4, rowspan=2, padx=(6, 0)
        )

    def _toggle_layout(self):
        self._compact = not self._compact
        self.layout_button.configure(text="Expand" if self._compact else "Compact")
        if self._compact:
            self.sidebar.grid_remove()
            self.geometry("740x620")
        else:
            self.sidebar.grid()
            self.geometry("1120x780")

    def _recall_request(self, _event=None):
        if not self.composer.get("1.0", "end-1c").strip() and self._last_request:
            self.composer.insert("1.0", self._last_request)
            return "break"

    def _build_workspace(self):
        workspace = ctk.CTkFrame(self, fg_color="transparent")
        workspace.grid(row=1, column=0, sticky="nsew", padx=22)
        workspace.grid_rowconfigure(0, weight=1)
        workspace.grid_columnconfigure(1, weight=1)
        self._build_sidebar(workspace)
        self._build_conversation(workspace)

    def _place_dialog(self, dialog, width, height):
        # A default +200+200 placement can hide Save below a laptop taskbar.
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        width = min(width, max(320, screen_width - 40))
        height = min(height, max(320, screen_height - 100))
        left = max(10, min(self.winfo_rootx() + (self.winfo_width() - width) // 2, screen_width - width - 20))
        top = max(10, min(self.winfo_rooty() + 40, screen_height - height - 70))
        dialog.geometry(f'{width}x{height}+{left}+{top}')

    def _build_sidebar(self, workspace):
        sidebar = ctk.CTkFrame(workspace, width=238, fg_color=PANEL, corner_radius=14,
                               border_color=LINE, border_width=1)
        self.sidebar = sidebar
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        if self._compact:
            sidebar.grid_remove()
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
        self._label(titlebar, "Ask anything", size=17, color=TEXT, bold=True).grid(row=0, column=0, sticky="w")
        self.session_label = self._label(titlebar, "THIS SESSION", size=10)
        self.session_label.grid(row=0, column=1, padx=10)
        self._button(titlebar, "Clear", self._clear_conversation, width=54).grid(row=0, column=2)
        self._button(titlebar, "Dictate", self._dictate, width=68).grid(row=0, column=3, padx=(6, 0))

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
        self.composer.bind("<Up>", self._recall_request)
        self.composer.bind("<Return>", self._composer_return)
        self.composer.bind("<Shift-Return>", self._composer_newline)
        self._button(composer_frame, "Send  ↗", self._send, primary=True, width=86).grid(row=0, column=1, padx=(6, 12))

        actions = ctk.CTkFrame(conversation, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="ew", padx=15, pady=(10, 14))
        actions.grid_columnconfigure(2, weight=1)
        self.live_caption = self._label(actions, "Ready when you are", size=11, anchor="w", wraplength=600)
        self.live_caption.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 4))
        self.live_level = ctk.CTkProgressBar(actions, height=3, progress_color=self.accent)
        self.live_level.grid(row=2, column=0, columnspan=3, sticky="ew")
        self.live_level.set(0)
        self.compact_wake_switch = ctk.CTkSwitch(actions, text=f'Listen for "{self.persona}"',
            variable=self._wake, command=self._toggle_wake, progress_color=self.accent,
            button_color=TEXT, font=(FONT, 11))
        self.compact_wake_switch.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.talk_button = self._button(actions, f"Talk to {self.name}", self._listen, width=145)
        self.talk_button.grid(row=0, column=0, sticky="w")
        self._button(actions, "Stop · Esc", self._stop, width=85).grid(row=0, column=1, padx=(7, 0))
        self._label(actions, "Enter to send · ↑ recall", size=10, anchor="e").grid(row=0, column=2, sticky="e", padx=(8, 0))

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
        self._message_serial += 1
        tag = f'message_{self._message_serial}'
        self.transcript.insert("end", str(text).strip() + "\n\n", (body_style, tag))
        if role in {'assistant', 'user'}:
            self.transcript.tag_bind(tag, '<Double-Button-1>',
                lambda _event, value=str(text), edit=role == 'user': self._reuse_message(value, edit))
        self.transcript.configure(state="disabled")
        if bottom or role == "user":
            self.transcript.see("end")
        if role in {"assistant", "user"}:
            self._message_count += 1
            self.session_label.configure(text=f"{self._message_count} MESSAGES")

    def _reuse_message(self, text, edit=False):
        if edit:
            self.composer.delete('1.0', 'end')
            self.composer.insert('1.0', text)
            self.composer.focus_set()
        else:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.live_caption.configure(text='Answer copied')
        return 'break'

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
            elif kind == 'text_preview':
                self._preview_text(event.get('title', 'Text preview'), event.get('text', ''))
            elif kind == 'shortcut_released':
                if self.controller.settings.shortcut_behavior == 'hold' and self._shortcut_finish is not None:
                    self._shortcut_finish.set()
            elif kind in {'voice_shortcut', 'dictation_shortcut'}:
                mode = self.controller.settings.shortcut_behavior
                if self._state == 'listening' and self._shortcut_finish is not None:
                    self._shortcut_finish.set()
                elif self._state in {'listening', 'transcribing', 'thinking', 'speaking'}:
                    self._shortcut_finish = None
                    self.controller.stop()
                else:
                    self._shortcut_finish = threading.Event() if mode != 'pause' else None
                    self._wake_overlay_session = True
                    hint = 'Release the shortcut to send' if mode == 'hold' else 'Press the shortcut again to send' if mode == 'toggle' else 'Speak, then pause to send'
                    self._overlay.show('listening', hint + ' · Esc cancels')
                    self._set_status('listening', hint)
                    if kind == 'dictation_shortcut':
                        self.controller.dictate_current(finish_signal=self._shortcut_finish)
                    else:
                        self.controller.listen_once(finish_signal=self._shortcut_finish)
            elif kind == "status":
                self._set_status(event.get("state", "standby"), event.get("detail", ""))
            elif kind == 'transcript_final':
                self.live_caption.configure(text='Heard: ' + event.get('text', '')[-160:])
            elif kind == 'transcript_partial':
                text = event.get('text', '')[-160:]
                self.detail_label.configure(text='Hearing: ' + text)
                self.live_caption.configure(text='Hearing: ' + text)
                self._overlay.set_phase('listening', text)
            elif kind == 'calibration':
                try:
                    self.controller.save_calibration(event['threshold'])
                except (OSError, ValueError):
                    self._append_message('system', 'Microphone tested, but its calibration could not be saved.')
            elif kind == 'mic_level':
                self.live_level.set(max(0, min(1, event.get('level', 0))))
                self.live_level.configure(progress_color=ERROR if event.get('clipping') else self.accent)
                dialog = getattr(self, '_dialog', None)
                if dialog is not None and dialog.winfo_exists() and hasattr(dialog, 'set_level'):
                    dialog.set_level(event.get('level', 0), event.get('clipping', False))
            elif kind == 'update_ready':
                if messagebox.askyesno('Update ready', 'The publisher signature and installer checksum are verified. Close this assistant and run the update?', parent=self):
                    try:
                        path = self.controller.prepare_update(event['path'])
                        os.startfile(str(path))
                        self._exit()
                        return
                    except (OSError, ValueError) as error:
                        self._append_message('system', str(error))
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
        self._schedule(120 if self._hidden_to_tray else 60, self._poll_events)

    def _preview_text(self, title, text):
        self._show_window()
        previous = getattr(self, '_text_preview', None)
        if previous is not None and previous.winfo_exists():
            previous.destroy()
        window = ctk.CTkToplevel(self)
        self._text_preview = window
        window.title(title)
        self._place_dialog(window, 650, 420)
        self._label(window, 'Review locally. Copy only when you are ready.', size=13).pack(pady=12)
        editor = ctk.CTkTextbox(window, wrap='word')
        editor.pack(fill='both', expand=True, padx=16, pady=8)
        editor.insert('1.0', text)
        def copy():
            self.clipboard_clear()
            self.clipboard_append(editor.get('1.0', 'end-1c'))
            window.destroy()
        self._button(window, 'Copy text', copy, width=110).pack(side='left', padx=16, pady=12)
        self._button(window, 'Discard', window.destroy, width=100).pack(side='right', padx=16, pady=12)

    def _dictate(self):
        dialog = ctk.CTkInputDialog(text='Which app should receive the text? Example: Notepad.\nClick its text field first if it has several.', title='Dictate into an app')
        app = dialog.get_input()
        if app and app.strip():
            self.controller.submit('dictate in ' + app.strip())

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
        if self._state != 'listening':
            self._shortcut_finish = None
        color = ERROR if self._state == "error" else self.accent
        self.state_label.configure(text=str(state).upper(), text_color=color)
        self.detail_label.configure(text=detail or {
            "ready": "Ready for your next request.", "standby": "Ready for a message.",
            "listening": "Listening to your microphone…", "transcribing": "Turning speech into text…",
            "thinking": "Working on your request…", "speaking": "Speaking. Press Esc to interrupt.",
            "error": "See the conversation for details.",
        }.get(self._state, ""))
        self.live_caption.configure(text=self.detail_label.cget("text"))
        if self._state not in {"listening", "transcribing"}:
            self.live_level.set(0)
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
            self._last_request = text
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
        self._shortcut_finish = None
        try:
            self.controller.listen_once()
        except Exception as exc:
            self._append_message("error", str(exc))

    def _stop(self, _event=None):
        self._shortcut_finish = None
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
        stt = {"auto": "Auto (Groq / Google)", "groq": "Groq", "google": "Google", "local": "Local", "deepgram": "Deepgram live"}.get(getattr(settings, "stt_provider", "auto"), "Auto")
        self.connection_label.configure(text=f"{'AI key configured' if configured else 'Add an AI key in Settings'} · {stt}")

    def _update_telemetry(self):
        if self._hidden_to_tray or self._compact:
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
        if self._hidden_to_tray or self._compact:
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

    def _open_setup(self):
        if self._dialog is not None and self._dialog.winfo_exists():
            self._dialog.lift()
            return
        self._dialog = SetupDialog(self)

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


class SetupDialog(ctk.CTkToplevel):
    """Three explicit setup steps; testing uses the existing microphone owner."""
    def __init__(self, parent):
        super().__init__(parent)
        self.parent, self.controller = parent, parent.controller
        self.step = 0
        self.devices = {'System default': (None, '')}
        self.results = queue.Queue()
        self.connection_results = queue.Queue()
        self.verifying = False
        self.title(f'{parent.name} · First-time setup')
        parent._place_dialog(self, 650, 580)
        self.minsize(560, 500)
        self.configure(fg_color=BG)
        self.transient(parent)
        self.heading = parent._label(self, '', size=22, bold=True, color=TEXT)
        self.heading.pack(padx=24, pady=20, anchor='w')
        self.body = ctk.CTkScrollableFrame(self, fg_color=PANEL)
        self.body.pack(fill='both', expand=True, padx=20)
        self.message = parent._label(self, '', size=11, wraplength=580)
        self.message.pack(padx=20, pady=8)
        self.next_button = parent._button(self, 'Next', self._next, primary=True)
        self.next_button.pack(side='right', padx=24, pady=16)
        self.later_button = parent._button(self, 'Set up later', self.destroy)
        self.later_button.pack(side='left', padx=24, pady=16)
        self._render()
        threading.Thread(target=lambda:self.results.put(self.controller.list_microphones()), daemon=True,
                         name='setup-device-list').start()
        parent._schedule(100, self._devices_ready)

    def _label(self, text):
        widget = self.parent._label(self.body, text, size=12, wraplength=555, justify='left', anchor='w')
        widget.pack(fill='x', padx=20, pady=9)
        return widget

    def _entry(self, text, value):
        self._label(text)
        entry = ctk.CTkEntry(self.body, show='•', height=35)
        entry.insert(0, value)
        entry.pack(fill='x', padx=20, pady=4)
        return entry

    def _render(self):
        for widget in self.body.winfo_children():
            widget.destroy()
        self.message.configure(text='')
        settings = self.controller.settings
        self.heading.configure(text=('1 / 3 · Your microphone', '2 / 3 · Your voice', '3 / 3 · Connections & privacy')[self.step])
        if self.step == 0:
            self._label('Choose an input. Test levels while speaking, then calibrate while the room is quiet. These tests stay on this PC.')
            self.microphone = ctk.CTkComboBox(self.body, values=list(self.devices), state='readonly', width=535)
            self.microphone.set(next((label for label, pair in self.devices.items()
                if pair[1] == settings.microphone_name and pair[0] == settings.microphone_index), 'System default'))
            self.microphone.pack(padx=20, pady=8)
            self.level_bar = ctk.CTkProgressBar(self.body, progress_color=self.parent.accent)
            self.level_bar.set(0)
            self.level_bar.pack(fill='x', padx=20, pady=14)
            self.parent._button(self.body, 'Save input & test levels', lambda:self._test(False), width=250).pack(pady=8)
            self.parent._button(self.body, 'Save input & calibrate', lambda:self._test(True), width=250).pack(pady=8)
            self._label('No microphone? You can still use text chat. Wake listening stays off until you enable it.')
        elif self.step == 1:
            self._label('Choose a neural speaking voice. The preview uses Edge online speech; Windows speech is the offline fallback.')
            self.voice = ctk.CTkComboBox(self.body, values=list(SettingsDialog.VOICES), width=535)
            self.voice.set(settings.voice)
            self.voice.pack(padx=20, pady=12)
            self.parent._button(self.body, 'Save voice & play preview', self._test_voice, width=260).pack(pady=12)
            self._label('Streaming replies start before the entire answer is generated. More voice and interruption options are in Settings.')
        else:
            self._label('Natural conversation needs an AI model. Enter your own Groq key to enable it. Local PC commands can run without a key, but open-ended questions and movie-style conversation will be unavailable.')
            self.groq = self._entry('Groq API key for natural conversation', settings.api_key)
            self._label('Create a key at https://console.groq.com/keys. The key is hidden, saved only in your personal app-data folder, and never included in releases or diagnostics.')
            self.provider = ctk.CTkComboBox(self.body, values=['local', 'auto', 'groq', 'google', 'deepgram'], state='readonly', width=535)
            self.provider.set(settings.stt_provider)
            self.provider.pack(padx=20, pady=9)
            self.language = ctk.CTkComboBox(self.body, values=['en-IN', 'hi-IN', 'auto'], state='readonly', width=535)
            self.language.set(settings.recognition_language)
            self.language.pack(padx=20, pady=6)
            self._label('hi-IN: Hindi · auto: Hindi + English detection (Groq/Deepgram). The local model supports English only.')
            self.deepgram = self._entry('Deepgram key for live transcription (optional)', settings.deepgram_api_key)
            self._label('Auto: Groq request audio with Google fallback. Deepgram: activated audio streamed to your account, with model-improvement opt-out; charges and provider retention terms apply. Settings keeps keys outside the project.')
            self.next_button.configure(text='Verify key & finish')
            self.later_button.configure(text='Use limited offline mode', command=self._finish_offline)

    def _devices_ready(self):
        if not self.winfo_exists():
            return
        try:
            devices = self.results.get_nowait()
        except queue.Empty:
            self.parent._schedule(100, self._devices_ready)
            return
        for index, name in devices:
            self.devices[f'{index} · {name}'] = (index, name)
        if self.step == 0:
            self._render()

    def set_level(self, level, clipping):
        if self.step == 0:
            self.level_bar.set(level)
            self.level_bar.configure(progress_color=ERROR if clipping else self.parent.accent)
            self.message.configure(text='Input is clipping. Lower the microphone level in Windows.' if clipping else 'Microphone level test (local only)')

    def _save_step(self):
        if self.step == 0:
            index, name = self.devices.get(self.microphone.get(), (None, ''))
            values = {'microphone_index':index, 'microphone_name':name}
        elif self.step == 1:
            values = {'voice':self.voice.get(), 'voice_provider':'edge'}
        else:
            if self.provider.get() == 'deepgram' and not self.deepgram.get().strip():
                raise ValueError('Enter your Deepgram key, or choose another recognition service.')
            values = {'api_key':self.groq.get().strip(), 'deepgram_api_key':self.deepgram.get().strip(),
                      'stt_provider':self.provider.get(), 'recognition_language':self.language.get(), 'setup_complete':False}
        if self.step != 2:
            self.controller.save_settings(values)
        return values

    def _finish_offline(self):
        if self.step != 2 or self.verifying:
            self.destroy()
            return
        try:
            if self.provider.get() == 'deepgram' and not self.deepgram.get().strip():
                self.provider.set('local')
                self.language.set('en-IN')
            self.groq.delete(0, 'end')
            values = self._save_step()
            self.controller.save_settings({**values, 'setup_complete':True})
            self.destroy()
        except (ValueError, OSError) as error:
            self.message.configure(text=str(error))

    def _connection_ready(self):
        if not self.winfo_exists():
            return
        try:
            success, message = self.connection_results.get_nowait()
        except queue.Empty:
            self.parent._schedule(100, self._connection_ready)
            return
        self.verifying = False
        if not success:
            self.next_button.configure(state='normal')
            self.later_button.configure(state='normal')
            self.message.configure(text=message)
            return
        try:
            self.controller.save_settings({**self.pending_connection_settings, 'setup_complete':True})
        except (ValueError, OSError) as error:
            self.next_button.configure(state='normal')
            self.later_button.configure(state='normal')
            self.message.configure(text=str(error))
            return
        self.destroy()

    def _test(self, calibrate):
        try:
            values = self._save_step()
            self.controller.calibrate_microphone() if calibrate else self.controller.test_microphone()
            self.message.configure(text='Stay quiet for two seconds.' if calibrate else 'Speak now for five seconds.')
        except (ValueError, OSError) as error:
            self.message.configure(text=str(error))

    def _test_voice(self):
        try:
            self._save_step()
            self.controller.test_voice()
        except (ValueError, OSError) as error:
            self.message.configure(text=str(error))

    def _next(self):
        try:
            values = self._save_step()
        except (ValueError, OSError) as error:
            self.message.configure(text=str(error))
            return
        if self.step == 2:
            key = self.groq.get().strip()
            if not key:
                self.message.configure(text='Enter your Groq API key for natural conversation, or choose limited offline mode.')
                return
            self.verifying = True
            self.pending_connection_settings = values
            self.next_button.configure(state='disabled')
            self.later_button.configure(state='disabled')
            self.message.configure(text='Verifying the AI connection…')
            def verify():
                try:
                    self.connection_results.put((True, self.controller.verify_ai_key(key)))
                except (ValueError, OSError) as error:
                    self.connection_results.put((False, str(error)))
            threading.Thread(target=verify, daemon=True, name='setup-ai-check').start()
            self.parent._schedule(100, self._connection_ready)
        else:
            self.step += 1
            self._render()


class SettingsDialog(ctk.CTkToplevel):
    """Scrollable configuration; no microphone enumeration on the Tk thread."""

    VOICES = ("en-US-EmmaMultilingualNeural", "en-IE-EmilyNeural", "en-GB-SoniaNeural", "en-GB-RyanNeural", "en-GB-ThomasNeural",
              "en-US-JennyNeural", "en-US-GuyNeural", "en-IN-NeerjaNeural", "en-IN-PrabhatNeural", "hi-IN-SwaraNeural", "hi-IN-MadhurNeural")
    GROQ_VOICES = ("autumn", "diana", "hannah", "austin", "daniel", "troy")

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.controller = parent.controller
        settings = self.controller.settings
        self.title(f"{parent.name} · Settings")
        self.configure(fg_color=BG)
        screen_height = self.winfo_screenheight()
        parent._place_dialog(self, 650, 735)
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
        from .ownership import details
        publisher = details(settings.persona)
        self._section('PROJECT PUBLISHER')
        self._hint(f"Created by {publisher['publisher']}\n{publisher['repository']}\nSigned release verification: see OWNERSHIP.md in the repository.")
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
        self._key_results = queue.Queue()
        self.verify_key_button = parent._button(content, 'Test this API key', self._verify_key, width=170)
        self.verify_key_button.grid(row=self._row, column=0, sticky='w', padx=14, pady=5)
        self._row += 1
        self._hint("Used for natural conversation and, if selected, Groq speech recognition.\nThe key is hidden here; it is never included in diagnostic output.")
        self.model = self._combo("Conversation model", settings.model, ("auto", "openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"))
        self.vision_model = self._entry('Screen understanding model', settings.vision_model)
        self._hint('“Look at my screen” sends one primary-screen image to Groq using your own key. Images and screen answers are not saved in history. There is no background screen sharing.')
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
        self.stt = self._combo("Speech recognition service", settings.stt_provider, ("auto", "local", "groq", "google", "deepgram"), readonly=True)
        self.deepgram_key = self._entry('Deepgram API key (optional)', settings.deepgram_api_key, show='•')
        self._hint('Deepgram streams activated requests for live transcription. It requires your own account and may incur usage charges. Model-improvement opt-out is enabled; provider pricing and retention terms apply. There is no automatic provider fallback.')
        self.language = self._combo("Listening language", settings.recognition_language, ('en-IN', 'hi-IN', 'auto', 'en-US', 'en-GB'))
        self._hint('Hindi: hi-IN. Hindi + English: auto with Groq or Deepgram. Auto service without a working Groq key falls back to Google Hindi. Hindi replies automatically use Swara (FRIDAY) or Madhur (ALFRED).')
        self._hint("Auto uses Groq Whisper with Google fallback. Online language examples: en-IN, en-GB, hi-IN.\nThe local wake detector listens for your assistant's name.")
        self._hint('Local streams English transcription without uploading the request. Auto shows a live local preview when the model is installed, then uses the selected online service for the final text.')
        self.microphone = self._combo("Microphone", self._mic_value, tuple(self._mic_values), readonly=True)
        self.level_bar = ctk.CTkProgressBar(content, progress_color=parent.accent)
        self.level_bar.set(0)
        self.level_bar.grid(row=self._row, column=0, sticky='ew', padx=14, pady=5)
        self._row += 1
        parent._button(content, 'Test saved microphone levels (5 seconds)', self.controller.test_microphone, width=300).grid(
            row=self._row, column=0, sticky='w', padx=14, pady=5)
        self._row += 1
        mic_actions = ctk.CTkFrame(content, fg_color="transparent")
        mic_actions.grid(row=self._row, column=0, sticky="ew", padx=14, pady=(0, 10))
        self._row += 1
        self.mic_status = parent._label(mic_actions, "Loading input devices…", size=10, anchor="w", wraplength=365)
        self.mic_status.pack(side="left", fill="x", expand=True)
        self.refresh_mics = parent._button(mic_actions, "Refresh", self._load_microphones, width=74)
        self.refresh_mics.pack(side="right")
        self.followup = self._entry("Follow-up listening (seconds)", str(settings.followup_seconds))
        self._hint("After a voice reply, keep listening for this long. Use 0 to turn follow-ups off.")
        parent._button(content, 'Test / calibrate saved microphone', lambda:self.controller.calibrate_microphone(), width=260).grid(
            row=self._row, column=0, sticky='w', padx=14, pady=8)
        self._row += 1
        self._hint('Save your microphone selection first. Then stay quiet for two seconds during calibration. Disconnected microphones fall back to Windows default and reconnect by device name.')
        self._section('RESPONSE SPEED & INTERRUPTION')
        self.global_voice_shortcut = self._switch('Global voice shortcut (Ctrl+Alt+A for ALFRED; Ctrl+Alt+F for FRIDAY)', settings.global_voice_shortcut)
        self.shortcut_behavior = self._combo('Shortcut behavior', settings.shortcut_behavior, ('hold', 'toggle', 'pause'), readonly=True)
        self._hint('Hold: release to send. Toggle: press again to send. Pause: finish after silence. Esc cancels. Add Shift to dictate into the focused field. At the recording limit, words appear for review without running commands.')
        self.streaming_voice = self._switch('Stream audio as it arrives', settings.streaming_voice)
        self.barge_in = self._switch('Allow spoken interruptions', settings.barge_in)
        self.noise_suppression = self._switch('Reduce background noise', settings.noise_suppression)
        self._hint('Spoken interruption needs the local model. Echo cancellation is available during streaming Edge playback; buffered/Windows fallback voices pause capture to avoid feedback.')
        self.wake_sensitivity = self._entry('Wake sensitivity (1–100; higher is more sensitive)', settings.wake_sensitivity)
        self.recognition_model = self._combo('Recognition accuracy', settings.recognition_model, ('whisper-large-v3', 'whisper-large-v3-turbo'), readonly=True)
        self._hint('Large v3 favors accuracy; turbo favors speed. Both use your cloud account. No model download.')
        self.pause_seconds = self._entry('Pause before ending a request (0.3–1.5 seconds)', settings.pause_seconds)
        self.echo_delay = self._entry('Speaker echo delay (0–300 ms)', settings.echo_delay_ms)
        self._section('SETUP & UPDATES')
        parent._button(content, 'Restore settings from before update', self._restore_update, width=280).grid(
            row=self._row, column=0, sticky='w', padx=14, pady=5)
        self._row += 1
        for title, action in (('Install local wake model', 'wake'), ('Check for updates', 'check'), ('Download verified update', 'download')):
            parent._button(content, title, lambda value=action:self.controller.maintenance(value), width=255).grid(
                row=self._row, column=0, sticky='w', padx=14, pady=5)
            self._row += 1
        self._hint('Wake detection stays on this PC; missing models never trigger online standby listening. Updates verify the pinned publisher signature and installer hash. A settings checkpoint is kept before installation; API keys and conversations stay in your personal data folder.')
        self._section('APP CONTEXT & ROUTINES')
        self._hint('Try “open Notepad then volume 30” or “when I say work, open Notepad then volume 30”.\nRun saved routines: work. Manage: list routines / delete routine work.\n“Read text in Chrome” opens a local text preview. “Look at my screen” requests a cloud image answer. “Dictate in Notepad” inserts literal speech into a chosen writable field without submitting it.')
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

    def _verify_key(self):
        key = self.api_key.get().strip()
        self.verify_key_button.configure(state='disabled')
        self.error_label.configure(text='Checking the key with Groq…', text_color=MUTED)
        def work():
            try:
                self._key_results.put((True, self.controller.verify_ai_key(key)))
            except Exception:
                self._key_results.put((False, 'The key could not be verified. Check the key, account and connection.'))
        threading.Thread(target=work, name='settings-key-check', daemon=True).start()
        self.parent._schedule(100, self._key_result)

    def _key_result(self):
        if not self.winfo_exists():
            return
        try:
            ok, message = self._key_results.get_nowait()
        except queue.Empty:
            self.parent._schedule(100, self._key_result)
            return
        self.verify_key_button.configure(state='normal')
        self.error_label.configure(text=message + (' Save to apply.' if ok else ''), text_color=self.parent.accent if ok else ERROR)

    def _section(self, text):
        self.parent._label(self._content, text, size=10, color=self.parent.accent, bold=True, anchor="w").grid(
            row=self._row, column=0, sticky="ew", padx=14, pady=(16, 9))
        self._row += 1

    def set_level(self, level, clipping):
        self.level_bar.set(level)
        self.level_bar.configure(progress_color=ERROR if clipping else self.parent.accent)

    def _restore_update(self):
        try:
            self.controller.restore_update_settings()
            self.destroy()
        except (OSError, ValueError) as error:
            self.error_label.configure(text=str(error), text_color=ERROR)

    def _switch(self, label, value):
        variable = tk.BooleanVar(master=self, value=bool(value))
        ctk.CTkSwitch(self._content, text=label, variable=variable, progress_color=self.parent.accent,
                      text_color=TEXT, font=(FONT, 12)).grid(row=self._row, column=0, sticky='w', padx=14, pady=7)
        self._row += 1
        return variable

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
                "vision_model": self.vision_model.get().strip(),
                "deepgram_api_key": self.deepgram_key.get().strip(),
                "voice_provider": self.voice_provider.get(),
                "groq_voice": self.groq_voice.get(),
                "voice": self.voice.get().strip(), "stt_provider": self.stt.get(),
                "recognition_language": self.language.get().strip(),
                "microphone_index": self._mic_values.get(self.microphone.get()),
                "followup_seconds": followup,
                "start_with_windows": self.start_with_windows.get(),
                "setup_complete": True,
                "streaming_voice": self.streaming_voice.get(),
                "global_voice_shortcut": self.global_voice_shortcut.get(),
                "barge_in": self.barge_in.get(),
                "noise_suppression": self.noise_suppression.get(),
                "wake_sensitivity": int(self.wake_sensitivity.get()),
                "pause_seconds": float(self.pause_seconds.get()),
                "recognition_model": self.recognition_model.get(),
                "shortcut_behavior": self.shortcut_behavior.get(),
                "echo_delay_ms": int(self.echo_delay.get()),
                "microphone_name": self.microphone.get().split(' · ', 1)[1] if ' · ' in self.microphone.get() else self.controller.settings.microphone_name if self._mic_values.get(self.microphone.get()) is not None else '',
            }
            self.controller.save_settings(values)
        except (ValueError, OSError) as exc:
            self.error_label.configure(text=str(exc), text_color=ERROR)
            return
        self.parent._refresh_config()
        self.parent._append_message("system", "Settings saved.")
        self.destroy()
