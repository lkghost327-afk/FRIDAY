"""One conversation worker and a queue-based boundary to the Tk main thread."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import queue
import re
import threading

from .actions import ActionRouter
from .brain import Brain, BrainError, Cancelled
from .memory import Memory
from .settings import Settings
from .voice import VoiceService
from .streaming import ReplySpeech


HELP = ("I can talk through questions, explain things, help you code, and keep track of our conversation. "
        "Try 'open Notepad', 'set volume to 40 percent', 'system status', 'take a screenshot', "
        "'take a note buy batteries', 'set a timer for 5 minutes', or 'weather in Mumbai'. "
        "Say 'remember that …' to save something about you. I can search the web for current information. "
        "Use Talk for one request, or enable Wake word to call my name and continue the conversation. "
        "Try 'minimize it', 'search Spotify for jazz', or 'list buttons in Notepad'. "
        "Save a routine with 'create routine work: open Notepad; volume 30', then say 'run routine work'. "
        "You can also say 'open Notepad then volume 30'. Try 'read text in Chrome' for a local text preview. "
        "Say 'dictate in Notepad' to insert literal speech into a chosen field, or 'look at my screen' for a cloud screen answer. "
        "Settings can enable global Talk and dictation shortcuts. "
        "Press Escape or say Stop to interrupt. Local recognition is available in Settings; AI chat uses the internet.")


class AssistantController:
    def __init__(self, base_dir, persona="friday", startup=None):
        self.base_dir = Path(base_dir).resolve()
        self.settings = Settings.load(self.base_dir, persona)
        self.startup = startup
        startup_error = None
        if self.startup is not None:
            try:
                self.settings = self.settings.updated({"start_with_windows": self.startup.refresh()})
            except (OSError, ValueError) as error:
                startup_error = error
        self.events = queue.Queue()
        self.memory = Memory(self.base_dir)
        self.brain = Brain(self.settings)
        self._lock = threading.RLock()
        self._busy = threading.Event()
        self._closed = threading.Event()
        self._cancel = threading.Event()
        self._jobs = queue.Queue(maxsize=1)
        self._wake_enabled = bool(self.settings.wake_on_start)
        self._started = False
        self._diagnosing = threading.Event()
        self._maintenance_busy = threading.Event()
        self.pending_update = None
        self.log = logging.getLogger("assistant." + persona)
        self.log.setLevel(logging.INFO)
        self.log.propagate = False
        if not self.log.handlers:
            (self.base_dir / "data").mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(self.base_dir / "data" / "assistant.log", maxBytes=1_000_000,
                                          backupCount=2, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self.log.addHandler(handler)
        self.voice = VoiceService(self.settings, self.emit)
        from .device_watch import DeviceWatch
        self._device_watch = DeviceWatch(self._device_event)
        from .hotkey import VoiceHotkey
        self._hotkey = VoiceHotkey(persona, self.emit)
        self.router = ActionRouter(self.base_dir, persona, self.emit)
        self.router.cancelled = lambda: self._cancel.is_set()
        if startup_error is not None:
            self.emit("notice", message=f"Windows startup could not be updated: {startup_error}")

    def emit(self, kind, **payload):
        if self._closed.is_set():
            return
        if kind == 'voice_cancel':
            self.stop()
            return
        if kind == 'status' and hasattr(self, '_hotkey'):
            if payload.get('state') in {'listening', 'transcribing', 'thinking', 'speaking'}:
                self._hotkey.cancel_enabled.set()
            else:
                self._hotkey.cancel_enabled.clear()
        if kind == "reminder":
            text = payload.get("text", "Reminder due.")
            self.events.put({"kind": "message", "role": "assistant", "text": text})
            self.voice.speak(text)
            return
        if kind == 'wake_detected' and hasattr(self.voice, 'metrics'):
            self.voice.metrics.count('wake_detections')
        # A cancelled voice operation must not overwrite a current model request's status.
        if kind == "status" and payload.get("state") in {"ready", "standby"} and self._busy.is_set():
            return
        self.events.put({"kind": kind, **payload})

    def start(self):
        if self._started:
            return
        self._started = True
        self._device_watch.start()
        if self.settings.global_voice_shortcut:
            self._hotkey.start()
        from .maintenance import recovery_status
        from . import __version__
        recovery = recovery_status(self.base_dir, __version__)
        if recovery:
            self.emit('notice', message=recovery)
        history, _ = self.memory.snapshot()
        for message in history:
            self.emit("message", role=message["role"], text=message["content"])
        if not history:
            greeting = ("At your service, Sir." if self.settings.persona == "alfred" else "Ready when you are, boss.")
            self.emit("message", role="assistant", text=greeting + " Type a message or press Talk. Settings has your microphone, voice, and AI connection.")
        if self.memory.warning:
            self.emit("notice", message=self.memory.warning)
        if not self.settings.api_key:
            self.emit("notice", message="Local commands are ready. Add a Groq API key in Settings for AI conversation.")
        self.voice.start(lambda text: self.submit(text, from_voice=True), self._busy.is_set)
        if self._wake_enabled:
            self.voice.set_wake_enabled(True)
        self._worker = threading.Thread(target=self._work, name="conversation", daemon=True)
        self._worker.start()
        self.emit("status", state="standby" if self._wake_enabled else "ready",
                  detail=f"Say {self.settings.persona}, followed by your question." if self._wake_enabled else "Type a message or press Talk")
        self.log.info("Started version %s; wake listening %s", __version__, "enabled" if self._wake_enabled else "disabled")
        def warmup():
            try:
                self.router._installed_apps()
                if self.settings.api_key and not self._closed.is_set():
                    self.brain.model()
            except Exception:
                pass
        threading.Thread(target=warmup, name="assistant-warmup", daemon=True).start()

    def _strip_name(self, text):
        from .voice import strip_wake_word
        detected, command = strip_wake_word(text, self.settings.persona)
        if detected:
            return command
        word = "alfred" if self.settings.persona == "alfred" else r"f\.?\s*r\.?\s*i\.?\s*d\.?\s*a\.?\s*y\.?"
        return re.sub(r"^(?:hey\s+|okay\s+|ok\s+)?" + word + r"\b[\s,.:!?]*", "", text, flags=re.I).strip()

    def submit(self, text, from_voice=False):
        text = self._strip_name(str(text).strip())
        if not text or self._closed.is_set():
            return
        if len(text) > 8000:
            self.emit("notice", message="Please keep each message under 8,000 characters.")
            return
        from .languages import is_stop
        if is_stop(text):
            self.stop()
            return
        if text.casefold().strip(".!?") in {"go to sleep", "stand by", "standby", "that's all", "that is all"}:
            self.stop()
            self.emit("message", role="assistant", text="Standing by. Say my name when you need me, or press Talk.")
            return
        with self._lock:
            self._cancel.set()
            self.voice.stop(preserve_conversation=from_voice)
            self._drain_jobs()
            current = threading.Event()
            self._cancel = current
            self._busy.set()
            self.emit("message", role="user", text=text)
            self.emit("status", state="thinking", detail="Working on your request")
            if hasattr(self.voice, 'metrics'):
                self.voice.metrics.begin()
            self._jobs.put_nowait((text, current))

    def _drain_jobs(self):
        while True:
            try:
                self._jobs.get_nowait()
                self._jobs.task_done()
            except queue.Empty:
                break

    def _local_reply(self, text):
        normalized = text.casefold().strip(" .!?")
        match = re.fullmatch(r'(?:read|show) (?:the )?(?:visible |screen )?text (?:in|from) (.+)', text.strip().rstrip('.!?'), re.I)
        if match:
            try:
                content = self.router.desktop.controls(match[1], 'read')
            except (ValueError, OSError, ImportError) as error:
                return f'App text could not be read: {error}'
            if not self.router.cancelled():
                self.emit('text_preview', title=f'Accessible text — {match[1]}', text=content)
            return 'App text is ready in a local preview. It was not sent to the conversation model. Some apps do not expose their text.'
        if normalized in {"help", "what can you do", "show commands", "commands", "what do you do"}:
            return HELP
        if normalized in {"who are you", "introduce yourself"}:
            return ("I'm Alfred, your Batman-inspired desktop assistant. At your service, Sir." if self.settings.persona == "alfred"
                    else "I'm FRIDAY, your Iron Man-inspired desktop assistant. Questions, ideas, and PC tasks—I'm here, boss.")
        match = re.match(r"^(?:please\s+)?remember (?:that\s+)?(.+)$", text, re.I | re.S)
        if match:
            return self.memory.remember(match.group(1))
        if normalized in {"what do you remember", "what do you remember about me", "show memories", "my memories"}:
            _, facts = self.memory.snapshot()
            return "Here's what you asked me to remember:\n" + "\n".join(facts) if facts else "You haven't asked me to remember anything yet."
        match = re.match(r"^forget (?:that\s+|about\s+)?(.+)$", text, re.I | re.S)
        if match:
            if match.group(1).casefold() in {"everything", "all memories", "all saved memories"}:
                self.memory.clear_facts()
                return "Your saved memories are cleared."
            return self.memory.forget(match.group(1))
        return self.router.handle(text)

    def _work(self):
        while not self._closed.is_set():
            try:
                text, cancel = self._jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            failed = False
            capture_started = False
            private_context = False
            speech = ReplySpeech(lambda text: self.voice.speak(text, prefetch=True))
            streamed = False
            def on_model_event(kind, **data):
                nonlocal speech, streamed
                if cancel.is_set():
                    return
                if kind == "speech_delta":
                    streamed = True
                    speech.feed(data["text"])
                elif kind == "speech_reset":
                    if speech.started:
                        self.voice.stop(preserve_conversation=True)
                    speech = ReplySpeech(lambda text: self.voice.speak(text, prefetch=True))
                    streamed = False
                else:
                    self.emit(kind, **data)
            try:
                if cancel.is_set():
                    continue
                self.router.cancelled = cancel.is_set
                from .screen_context import is_screen_question, capture_screen
                dictation = re.fullmatch(r'dictate (?:in|into|to) (.+)', text.strip().rstrip('.!?'), re.I)
                if dictation:
                    capture_started = self._begin_target_dictation(dictation[1], cancel)
                    continue
                if is_screen_question(text):
                    if not self.settings.api_key:
                        raise BrainError('Add your Groq key in Settings before asking about the screen.')
                    from .automation_worker import isolated
                    self.emit('notice', message='Your explicit screen request sends one primary-screen image to Groq using your account. The image is not saved.')
                    picture = isolated(capture_screen, (), cancel.is_set)
                    private_context = True
                    try:
                        answer = self.brain.answer_screen(text, picture, cancel, on_model_event)
                    finally:
                        picture = None
                else:
                    answer = self._local_reply(text)
                if answer is None:
                    history, facts = self.memory.snapshot()
                    brain = self.brain
                    answer = brain.answer(text, history, facts, self.router, cancel,
                                          on_model_event)
                with self._lock:
                    if cancel.is_set() or self._closed.is_set():
                        continue
                    try:
                        if not private_context:
                            self.memory.add_turn(text, answer)
                    except OSError:
                        self.emit("notice", message="I answered, but couldn't save this conversation to disk.")
                    self.emit("message", role="assistant", text=answer)
                    if streamed:
                        speech.finish()
                    else:
                        self.voice.speak(answer)
            except Cancelled:
                pass
            except BrainError as error:
                failed = True
                if not cancel.is_set():
                    self.emit("message", role="assistant", text=str(error))
                    self.emit("status", state="error", detail="Check Settings or run Diagnostics")
                    self.log.warning("AI request failed with a user-visible connection message")
            except Exception as error:
                if not cancel.is_set():
                    self.emit("notice", message="This request couldn't be completed. Try again or run Diagnostics.")
                    self.log.error("Request failed: %s", type(error).__name__)
            finally:
                with self._lock:
                    if self._cancel is cancel:
                        self._busy.clear()
                        if not failed and not capture_started and not self.voice.busy.is_set():
                            self.emit("status", state="ready", detail="Type a message or press Talk")
                self._jobs.task_done()

    def listen_once(self, finish_signal=None):
        self.stop(announce=False)
        self.voice.listen_once(finish_signal=finish_signal)

    def dictate_once(self):
        self.stop(announce=False)
        self.emit('wake_detected', detail='Dictating — words will not run commands')
        self.voice.listen_once(dictation=True)

    def dictate_current(self, finish_signal=None):
        self.stop(announce=False)
        with self._lock:
            cancel = threading.Event()
            self._cancel = cancel
            self._busy.set()
        def prepare():
            try:
                self._begin_target_dictation("current app", cancel, finish_signal)
            finally:
                with self._lock:
                    if self._cancel is cancel:
                        self._busy.clear()
        threading.Thread(target=prepare, name="dictation-prepare", daemon=True).start()

    def _begin_target_dictation(self, app, cancel, finish_signal=None):
        try:
            binding = self.router.desktop.prepare_dictation(app)
        except (ValueError, OSError, ImportError) as error:
            self.emit('notice', message=str(error))
            return False
        if cancel.is_set():
            return False
        self.emit('wake_detected', detail='Dictation into ' + app)
        mode = 'at the selected caret' if binding['field']['mode'] == 'selection' else 'at the end of the chosen field'
        self.emit('notice', message=f'Dictating into {app}, {mode}. Text is inserted literally; nothing is submitted.')
        self.voice.listen_once(dictation=True, on_dictation=lambda text: self._insert_dictation(binding, text, cancel), finish_signal=finish_signal)
        return True

    def _insert_dictation(self, binding, text, cancel):
        def work():
            from .automation_worker import isolated
            from .dictation import insert
            with self._lock:
                if cancel.is_set() or self._closed.is_set():
                    return
                self._busy.set()
            try:
                self.emit('status', state='thinking', detail='Inserting dictation')
                result = isolated(insert, (binding, text), cancel.is_set)
                if not cancel.is_set():
                    self.emit('notice', message=result)
            except (ValueError, OSError, ImportError) as error:
                if not cancel.is_set():
                    self.emit('notice', message=str(error))
                    self.emit('text_preview', title='Dictation was not confirmed — check the app before copying', text=text)
            finally:
                with self._lock:
                    if self._cancel is cancel:
                        self._busy.clear()
                        self.emit('status', state='ready', detail='Dictation finished')
        threading.Thread(target=work, name='dictation-insert', daemon=True).start()

    def set_wake_enabled(self, enabled, persist=True):
        self._wake_enabled = bool(enabled)
        if persist and self.settings.wake_on_start != self._wake_enabled:
            settings = self.settings.updated({"wake_on_start": self._wake_enabled})
            settings.save(self.base_dir)
            self.settings = settings
            self.brain.settings = settings
            self.voice.settings = settings
            self.emit("config")
        self.voice.set_wake_enabled(self._wake_enabled)

    def stop(self, announce=True):
        with self._lock:
            self._cancel.set()
            self._drain_jobs()
            self._busy.clear()
            self.voice.stop()
            self.router.power.cancel()
        if announce:
            self.emit("status", state="ready", detail="Stopped. Ready for your next request")

    def save_settings(self, values):
        settings = self.settings.updated(values)
        startup_changed = False
        previous_command = None
        if "start_with_windows" in values:
            if self.startup is None and settings.start_with_windows:
                raise ValueError("Open the assistant normally to enable Start with Windows.")
            if self.startup is not None:
                previous_command = self.startup.get_command()
                self.startup.set_enabled(settings.start_with_windows)
                startup_changed = True
        try:
            settings.save(self.base_dir)
        except Exception:
            if startup_changed:
                try:
                    self.startup.restore(previous_command)
                except OSError as error:
                    raise OSError("Settings could not be saved and Windows startup could not be restored. "
                                  "Review Start with Windows before closing Settings.") from error
            raise
        self.stop(announce=False)
        self.settings = settings
        self.brain = Brain(settings)
        self.voice.update_settings(settings)
        self._hotkey.close()
        if settings.global_voice_shortcut and self._started:
            self._hotkey.start()
        self._wake_enabled = bool(settings.wake_on_start)
        if self._wake_enabled:
            self.voice.set_wake_enabled(True)
        self.emit("config")
        self.emit("notice", message="Settings saved.")

    def list_microphones(self):
        return self.voice.list_microphones()

    def calibrate_microphone(self):
        self.stop(announce=False)
        self.voice.calibrate()

    def test_microphone(self):
        self.stop(announce=False)
        self.voice.test_microphone()

    def _device_event(self, event):
        if self._closed.is_set():
            return
        self.stop(announce=False)
        self.router.desktop.last_app = None
        self.router.desktop.selections.clear()
        if event == 'suspend':
            self.voice._suspended.set()
            self.emit('status', state='standby', detail='Windows is suspending')
            return
        self.voice._suspended.clear()
        self.voice.recover_devices()
        self.emit('notice', message='Audio devices refreshed. Previous requests were cancelled; wake listening follows your saved preference.')
        self.emit('status', state='standby' if self._wake_enabled else 'ready', detail='Ready after device recovery')

    def prepare_update(self, path):
        from .maintenance import prepare_install
        from . import __version__
        if self.pending_update is None:
            raise ValueError('Check for updates and download the verified installer first.')
        return prepare_install(path, self.pending_update, self.base_dir, __version__)

    def restore_update_settings(self):
        from .maintenance import restore_settings
        settings = restore_settings(self.base_dir, self.settings.persona)
        from dataclasses import asdict
        values = asdict(settings)
        values.pop('persona')
        self.save_settings(values)

    def save_calibration(self, threshold):
        self.settings = self.settings.updated({'microphone_threshold': threshold})
        self.settings.save(self.base_dir)
        self.emit('notice', message=f'Microphone calibrated. Background-noise threshold: {threshold}.')

    def maintenance(self, action):
        if self._maintenance_busy.is_set():
            self.emit('notice', message='Setup or update work is already running.')
            return
        self._maintenance_busy.set()
        def work():
            from .maintenance import install_wake, check_update, download_update
            from . import __version__
            try:
                if action == 'wake':
                    message = install_wake(lambda text:self.emit('notice', message=text), self._closed.is_set)
                    self.voice._local_wake_failed = False
                    self.emit('notice', message=message)
                elif action == 'check':
                    self.pending_update = check_update(self.settings.persona, __version__)
                    self.emit('notice', message=f'Update {self.pending_update["version"]} is available. Use Download update in Settings.'
                              if self.pending_update else 'No newer stable installer is published.')
                elif action == 'download':
                    if not self.pending_update:
                        raise ValueError('Check for updates first.')
                    path = download_update(self.pending_update, self.base_dir/'updates', self._closed.is_set)
                    self.emit('update_ready', path=str(path))
            except Exception as error:
                self.emit('notice', message=f'Setup/update could not finish ({type(error).__name__}). Your existing installation is unchanged.')
                self.log.warning('Maintenance failure: %s', type(error).__name__)
            finally:
                self._maintenance_busy.clear()
        threading.Thread(target=work, name='assistant-maintenance', daemon=True).start()

    def test_voice(self):
        if not self.settings.speech_enabled:
            self.emit("notice", message="Turn on spoken replies to test the voice.")
            return
        self.stop(announce=False)
        self.voice.speak("At your service, Sir. Your voice system is ready." if self.settings.persona == "alfred"
                         else "Voice check. Ready when you are, boss.")

    def verify_ai_key(self, key):
        """Verify a candidate key without replacing the active settings first."""
        key = str(key or '').strip()
        if not key:
            raise ValueError('Enter your Groq API key, or choose limited offline mode.')
        candidate = self.settings.updated({'api_key': key})
        try:
            return Brain(candidate).check_connection()
        except BrainError as error:
            raise ValueError(str(error)) from None

    def diagnostics(self):
        if self._diagnosing.is_set():
            return
        self._diagnosing.set()
        def check():
            import json
            import psutil
            self.emit("notice", message="Checking audio devices and the AI connection…")
            try:
                names = self.list_microphones()
                lines = [f"Microphone inputs: {len(names)} available.",
                         f"Speech recognition: {self.settings.stt_provider}; language: {self.settings.recognition_language}.",
                         f"Voice: {self.settings.voice_provider} / {self.settings.voice}; spoken replies {'on' if self.settings.speech_enabled else 'off'}.",
                         f"Background wake at startup: {'on' if self.settings.wake_on_start else 'off'}."]
                if hasattr(self.voice, 'metrics'):
                    process = psutil.Process()
                    lines.append(f'Assistant RAM: {process.memory_info().rss / (1024*1024):.1f} MB; CPU over 1 second: {process.cpu_percent(interval=1):.1f}%.')
                    lines.append('Recent performance (no transcripts): ' + json.dumps(self.voice.metrics.summary()))
                try:
                    lines.append(self.brain.check_connection())
                except BrainError as error:
                    lines.append(str(error))
                self.emit("notice", message="\n".join(lines))
            except Exception as error:
                self.emit("notice", message="Diagnostics could not finish. Check your audio device and Settings.")
                self.log.warning("Diagnostics failed: %s", type(error).__name__)
            finally:
                self._diagnosing.clear()
        threading.Thread(target=check, name="diagnostics", daemon=True).start()

    def clear_conversation(self):
        self.stop(announce=False)
        self.memory.clear_history()
        self.emit("clear")
        self.emit("notice", message="Conversation cleared. Explicitly saved memories are kept.")

    def clear_memories(self):
        self.stop(announce=False)
        self.memory.clear_facts()
        self.emit("notice", message="Saved memories cleared.")

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        self._device_watch.close()
        self._hotkey.close()
        self.stop(announce=False)
        self.voice.close()
        self.router.close()
        self.log.info("Closed cleanly")
