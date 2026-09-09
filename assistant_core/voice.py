"""One microphone owner and cancellable speech for both assistant personas.

Importing this module never opens the microphone, starts audio, or needs a key.
Wake listening is opt-in. Recognition uses an online service, not an offline
wake-word detector; the settings screen should make that clear.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import Future
import importlib.util
import os
import queue
import re
import tempfile
import threading
import time
from typing import Callable


class _Cancelled(Exception):
    pass


class _InterruptibleStream:
    """Allow cancellation between PortAudio reads, including mid-utterance."""

    def __init__(self, stream, valid):
        self._stream = stream
        self._valid = valid

    def read(self, size):
        if not self._valid():
            raise _Cancelled()
        data = self._stream.read(size)
        if not self._valid():
            raise _Cancelled()
        return data

    def close(self):
        return self._stream.close()


def strip_wake_word(text: str, persona: str) -> tuple[bool, str]:
    """Preserve a question spoken in the same breath as the assistant name."""
    name = r"(?:friday|fry\s+day|for\s+i\s+day)" if persona.lower() == "friday" else r"(?:alfred|al\s+fred)"
    match = re.match(r"^\s*(?:(?:hey|hi|hello|okay|ok)\s+)?" + name + r"\b[\s,.:;!?-]*", text, re.I)
    return (True, text[match.end():].strip()) if match else (False, text.strip())


def text_for_speech(text: str) -> str:
    """Read prose naturally while leaving code and full citations on screen."""
    original = str(text or "").strip()
    if not original:
        return ""
    text = re.sub(r"```[^\n]*\n?.*?```", " I've put the code in the conversation. ", original, flags=re.S)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\(https?://[^\s)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?m)^\s*\|?[\s:|-]+\|\s*$", "", text)
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s+|>\s*|[-*+]\s+)", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"(?<!\w)[*_]([^*_\n]+)[*_](?!\w)", r"\1", text)
    text = text.replace("|", ", ")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 1400:
        end = max(text.rfind(". ", 850, 1325), text.rfind("? ", 850, 1325), text.rfind("! ", 850, 1325))
        if end < 0:
            end = text.rfind(" ", 0, 1325)
        text = text[:end + 1].rstrip() + " The rest is in the conversation."
    return text or "I've put the details in the conversation."


def split_speech(text: str, limit: int = 300) -> list[str]:
    """Build short sentence-led segments so speech can begin promptly."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return []
    limit = max(80, int(limit))
    units = re.split(r"(?<=[.!?])\s+", text)
    pieces = []
    for unit in units:
        while len(unit) > limit:
            cut = max(unit.rfind(mark, 0, limit + 1) for mark in ("; ", ", ", ": ", " — ", " - "))
            if cut < limit // 3:
                cut = unit.rfind(" ", 0, limit + 1)
            if cut < 1:
                cut = limit
            else:
                cut += 1
            pieces.append(unit[:cut].strip())
            unit = unit[cut:].strip()
        if unit:
            pieces.append(unit)
    combined = []
    for piece in pieces:
        if combined and len(combined[-1]) + len(piece) + 1 <= limit:
            combined[-1] += " " + piece
        else:
            combined.append(piece)
    return combined


class VoiceService:
    def __init__(self, settings, emit: Callable):
        self.settings = settings
        self.emit = emit
        self.busy = threading.Event()
        self._output_active = threading.Event()
        self._closed = threading.Event()
        self._listen_request = threading.Event()
        self._lock = threading.RLock()
        self._speech_queue = queue.Queue()
        self._render_queue = queue.Queue()
        self._prepared = {}
        self._speech_generation = 0
        self._capture_generation = 0
        self._speech_pending = 0
        self._wake_enabled = False
        self._conversation_active = False
        self._followup_until = 0.0
        self._await_response_since = 0.0
        self._response_started = False
        self._started = False
        self._threads = []
        self._on_transcript = lambda text: None
        self._is_busy = lambda: False
        self._status_key = None
        self._last_notice = {}
        self._cloud_retry_after = 0.0
        self._groq_retry_after = 0.0
        self._stt_retry_after = 0.0
        self._sapi = None
        self._pygame = None
        self._com_initialized = False
        self._energy_threshold = 300
        self._local_wake = None
        self._local_wake_failed = False
        self._local_wake_heard = False
        self._microphone_failures = 0
        self.available = self._has_module("speech_recognition") and self._has_module("pyaudio")

    @staticmethod
    def _has_module(name):
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            return False

    def _setting(self, name, default=None):
        if isinstance(self.settings, dict):
            return self.settings.get(name, default)
        return getattr(self.settings, name, default)

    def _emit(self, kind, **payload):
        try:
            self.emit(kind, **payload)
        except Exception:
            pass  # A closing UI must never crash an audio worker.

    def _status(self, state, detail=""):
        key = (state, detail)
        if self._status_key != key:
            self._status_key = key
            self._emit("status", state=state, detail=detail)

    def _notice(self, message, cooldown=30):
        now = time.monotonic()
        if now - self._last_notice.get(message, -10000) >= cooldown:
            self._last_notice[message] = now
            self._emit("notice", message=message)

    def start(self, on_transcript: Callable[[str], None], is_busy: Callable[[], bool]):
        self._on_transcript = on_transcript
        self._is_busy = is_busy
        with self._lock:
            if self._started or self._closed.is_set():
                return
            self._started = True
            self._threads = [
                threading.Thread(target=self._capture_loop, name="assistant-microphone", daemon=True),
                threading.Thread(target=self._speech_loop, name="assistant-speaker", daemon=True),
                threading.Thread(target=self._prepare_loop, name="assistant-voice-render-1", daemon=True),
                threading.Thread(target=self._prepare_loop, name="assistant-voice-render-2", daemon=True),
            ]
            for worker in self._threads:
                worker.start()

    @staticmethod
    def list_microphones() -> list[tuple[int, str]]:
        try:
            import pyaudio
            audio = pyaudio.PyAudio()
            try:
                return [(index, str(info["name"]))
                        for index in range(audio.get_device_count())
                        if (info := audio.get_device_info_by_index(index)).get("maxInputChannels", 0) > 0]
            finally:
                audio.terminate()
        except Exception:
            return []

    def listen_once(self):
        if self._closed.is_set():
            return
        if not self.available:
            self._notice("Microphone support is unavailable. Run setup.bat to install SpeechRecognition and PyAudio, or use text.")
            return
        self.stop()
        with self._lock:
            self._conversation_active = True
            self._listen_request.set()

    def set_wake_enabled(self, enabled: bool):
        with self._lock:
            self._wake_enabled = bool(enabled) and self.available
            self._capture_generation += 1
            if not enabled:
                self._followup_until = 0
                self._conversation_active = False
                self._listen_request.clear()
        self._emit("wake", enabled=self._wake_enabled)
        if enabled and not self.available:
            self._notice("Wake listening needs SpeechRecognition and PyAudio. Text chat remains available.")
        elif enabled:
            self._notice("Wake listening is on. The local detector listens for my name; your requests use the selected online transcription service.", cooldown=30)
        else:
            self._status("ready", "Microphone off. Press Talk or type a message.")

    def update_settings(self, settings):
        self.stop()
        with self._lock:
            self.settings = settings
            self._cloud_retry_after = 0
            self._groq_retry_after = 0
            self._stt_retry_after = 0
            self._energy_threshold = 300
            self._local_wake_failed = False
        self.available = self._has_module("speech_recognition") and self._has_module("pyaudio")

    def stop(self, preserve_conversation=False):
        """Invalidate pending work; active stream/playback cancels at next read."""
        with self._lock:
            self._speech_generation += 1
            self._capture_generation += 1
            self._speech_pending = 0
            for futures in self._prepared.values():
                for future in futures:
                    if not future.cancel() and future.done():
                        self._discard_prepared(future)
            self._prepared.clear()
            # Drop superseded queue entries immediately instead of letting a
            # long cancelled answer delay the next request or retain its text.
            for pending_queue in (self._speech_queue, self._render_queue):
                while True:
                    try:
                        pending_queue.get_nowait()
                    except queue.Empty:
                        break
            self.busy.clear()
            self._listen_request.clear()
            self._followup_until = 0
            if not preserve_conversation:
                self._conversation_active = False
            self._await_response_since = time.monotonic() if self._conversation_active else 0
            self._response_started = False

    def close(self):
        self._closed.set()
        self.stop()
        self._speech_queue.put(None)
        self._render_queue.put(None)
        self._render_queue.put(None)
        # Workers have bounded network/read waits and daemon lifetimes. The UI
        # remains responsive while they release their own microphone/audio objects.

    def _model_busy(self):
        try:
            return bool(self._is_busy())
        except Exception:
            return False

    def _capture_valid(self, generation):
        return (not self._closed.is_set() and generation == self._capture_generation
                and not self.busy.is_set() and not self._output_active.is_set() and not self._model_busy())

    def _arm_followup(self):
        with self._lock:
            self._await_response_since = 0
            self._response_started = False
            if self._conversation_active:
                seconds = max(0, min(60, int(self._setting("followup_seconds", 15))))
                self._followup_until = time.monotonic() + seconds

    def _capture_loop(self):
        while not self._closed.is_set():
            if not self.available:
                self._closed.wait(0.3)
                continue
            model_busy = self._model_busy()
            if self._await_response_since:
                if model_busy:
                    self._response_started = True
                if (not model_busy and not self.busy.is_set() and not self._output_active.is_set()
                        and (self._response_started or time.monotonic() - self._await_response_since > 1.0)):
                    self._arm_followup()
                else:
                    self._closed.wait(0.05)
                    continue
            if model_busy or self.busy.is_set() or self._output_active.is_set():
                self._closed.wait(0.05)
                continue
            with self._lock:
                requested = self._listen_request.is_set()
                followup = time.monotonic() < self._followup_until
                wake = self._wake_enabled
                generation = self._capture_generation
                if requested:
                    self._listen_request.clear()
            if not (requested or followup or wake):
                self._local_wake = None
                self._status("ready", "Microphone off. Press Talk or type a message.")
                self._closed.wait(0.1)
                continue
            if requested or followup:
                self._status("listening", "Speak now. Listening for your message…")
            else:
                name = str(self._setting("persona", "friday")).upper()
                self._status("standby", f"Say {name}, followed by your question.")
            try:
                self._local_wake_heard = False
                transcript = self._capture_and_transcribe(generation, requested, followup)
                self._microphone_failures = 0
                if not transcript or not self._capture_valid(generation):
                    continue
                detected, command = strip_wake_word(transcript, str(self._setting("persona", "friday")))
                if not (requested or followup or detected or self._local_wake_heard):
                    continue
                if detected and not self._local_wake_heard:
                    self._emit("wake_detected", command=command)
                if not detected:
                    command = transcript.strip()
                with self._lock:
                    self._conversation_active = True
                if not command:
                    self._arm_followup()
                    self._status("listening", "I'm listening. Ask your question.")
                    continue
                with self._lock:
                    self._await_response_since = time.monotonic()
                    self._response_started = False
                    self._followup_until = 0
                self._on_transcript(command)
            except _Cancelled:
                pass
            except Exception:
                self._microphone_failures += 1
                self._notice("The microphone is temporarily unavailable. I will retry automatically. Check the selected input in Settings if this continues.")
                self._status("error", "Reconnecting microphone…")
                self._closed.wait(min(10, self._microphone_failures))

    def _listen_for_local_wake(self, source, generation):
        from .wake import LocalWake, ReplayStream, model_directory
        if self._local_wake_failed:
            return False
        if self._local_wake is None:
            try:
                if not (model_directory() / "am/final.mdl").is_file():
                    raise FileNotFoundError()
                self._local_wake = LocalWake(self._setting("persona", "friday"))
            except Exception:
                self._local_wake_failed = True
                self._notice("Local wake detection is unavailable. Run Setup.bat to install its model. Using online wake recognition in the meantime.", cooldown=300)
                return False
        self._local_wake.reset()
        while self._capture_valid(generation):
            frames = self._local_wake.feed(source.stream.read(source.CHUNK))
            if frames is not None:
                self._local_wake_heard = True
                self._emit("wake_detected", command="")
                self._status("listening", "I'm listening…")
                source.stream = ReplayStream(source.stream, frames)
                return True
        raise _Cancelled()

    def _capture_and_transcribe(self, generation, requested, followup):
        import speech_recognition as sr
        recognizer = sr.Recognizer()
        recognizer.operation_timeout = 12
        recognizer.pause_threshold = 0.65
        recognizer.non_speaking_duration = 0.4
        recognizer.dynamic_energy_threshold = True
        recognizer.energy_threshold = self._energy_threshold
        try:
            with sr.Microphone(device_index=self._setting("microphone_index"), sample_rate=16000, chunk_size=512) as source:
                source.stream = _InterruptibleStream(source.stream, lambda: self._capture_valid(generation))
                if not requested and not followup:
                    self._listen_for_local_wake(source, generation)
                # Learn from silence inside listen(); a separate calibration read
                # consumes the start of a command spoken immediately after Talk.
                try:
                    audio = recognizer.listen(source, timeout=7 if requested or self._local_wake_heard else 1, phrase_time_limit=30)
                finally:
                    self._energy_threshold = recognizer.energy_threshold
        except sr.WaitTimeoutError:
            if requested:
                self._status("ready", "No speech heard. Press Talk to try again.")
            return ""
        if not self._capture_valid(generation):
            raise _Cancelled()
        self._status("transcribing", "Recognizing speech…")
        try:
            if (self._setting("stt_provider", "auto") in {"groq", "auto"}
                    and self._setting("api_key", "") and time.monotonic() >= self._stt_retry_after):
                key = str(self._setting("api_key", "") or "").strip()
                if not key:
                    self._notice("Groq transcription needs your Groq API key. Choose Google recognition in Settings or add the key.")
                    return ""
                from groq import Groq
                language = str(self._setting("recognition_language", "en-IN")).split("-")[0]
                try:
                    with Groq(api_key=key, timeout=8, max_retries=0) as client:
                        result = client.audio.transcriptions.create(
                            file=("command.wav", audio.get_wav_data(convert_rate=16000), "audio/wav"),
                            model="whisper-large-v3-turbo", language=language, response_format="verbose_json",
                            temperature=0,
                            prompt="FRIDAY, Alfred, Spotify, Discord, WhatsApp, Visual Studio Code, Steam, Chrome, Notepad, calculator.")
                    segments = getattr(result, "segments", None) or []
                    if segments and all(float(s.get("no_speech_prob", 0)) > 0.75 for s in segments):
                        return ""
                    return str(getattr(result, "text", "")).strip()
                except Exception:
                    self._stt_retry_after = time.monotonic() + 30
                    self._notice("Groq recognition is unavailable. Trying Google recognition for this request.", cooldown=60)
            return recognizer.recognize_google(audio, language=self._setting("recognition_language", "en-IN")).strip()
        except sr.UnknownValueError:
            if requested or followup:
                self._status("ready", "I didn't catch that. Please try again.")
            return ""
        except Exception:
            self._notice("Speech recognition could not connect. Check the network and transcription settings, or type your message.")
            # Prevent continuous requests while the provider is unavailable.
            self._closed.wait(2)
            return ""

    def speak(self, text: str, prefetch=False):
        text = text_for_speech(text)
        if not text or self._closed.is_set():
            return
        if not self._setting("speech_enabled", True):
            self._arm_followup()
            return
        with self._lock:
            if prefetch and len(text) <= 310 and self._setting("voice_provider", "edge") == "edge" and time.monotonic() >= self._cloud_retry_after:
                generation = self._speech_generation
                future = Future()
                self._prepared.setdefault((generation, text), []).append(future)
                future.add_done_callback(lambda done, token=generation: self._discard_prepared(done) if not self._speech_valid(token) else None)
                self._render_queue.put((generation, text, future))
            self._speech_pending += 1
            self.busy.set()
            self._capture_generation += 1
            self._speech_queue.put((self._speech_generation, text))

    def _speech_valid(self, generation):
        return not self._closed.is_set() and generation == self._speech_generation

    @staticmethod
    def _discard_prepared(future):
        try:
            path = future.result()
            os.unlink(path)
        except Exception:
            pass

    def _prepare_loop(self):
        while not self._closed.is_set():
            item = self._render_queue.get()
            if item is None:
                return
            generation, text, future = item
            if not self._speech_valid(generation) or not future.set_running_or_notify_cancel():
                future.cancel()
                continue
            path = None
            try:
                if time.monotonic() < self._cloud_retry_after:
                    raise OSError("Online voice is cooling down")
                descriptor, path = tempfile.mkstemp(prefix="assistant-speech-", suffix=".mp3")
                os.close(descriptor)
                self._render_cloud(text, path, generation)
                if not self._speech_valid(generation):
                    raise _Cancelled()
                future.set_result(path)
                path = None
            except Exception as error:
                future.set_exception(error)
            finally:
                if path:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

    def _speech_loop(self):
        try:
            while not self._closed.is_set():
                item = self._speech_queue.get()
                if item is None:
                    break
                generation, text = item
                if not self._speech_valid(generation):
                    continue
                self._status("speaking", "Preparing voice…")
                try:
                    self._speak_job(text, generation)
                except _Cancelled:
                    pass
                except Exception:
                    self._notice("Audio output is unavailable. The complete answer is still shown in the conversation.")
                finally:
                    with self._lock:
                        if generation == self._speech_generation:
                            self._speech_pending = max(0, self._speech_pending - 1)
                            if not self._speech_pending:
                                self.busy.clear()
                                self._arm_followup()
                                if not self._model_busy():
                                    self._status("ready", "Ready for your next question.")
        finally:
            if self._pygame is not None:
                try:
                    self._pygame.mixer.quit()
                except Exception:
                    pass
            if self._com_initialized:
                try:
                    self._sapi = None
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    def _speak_job(self, text, generation):
        with self._lock:
            futures = self._prepared.get((generation, text), [])
            prepared = futures.pop(0) if futures else None
            if not futures:
                self._prepared.pop((generation, text), None)
        if prepared is not None:
            path = None
            try:
                while not prepared.done():
                    if not self._speech_valid(generation):
                        raise _Cancelled()
                    self._closed.wait(0.02)
                path = prepared.result()
                if not self._speech_valid(generation):
                    raise _Cancelled()
                self._play_file(path, generation)
                return
            except _Cancelled:
                raise
            except Exception:
                if not self._speech_valid(generation):
                    raise _Cancelled()
                self._cloud_retry_after = time.monotonic() + 60
                self._notice("Online voice is unavailable. Using the installed Windows voice.", cooldown=60)
                self._speak_windows(text, generation)
                return
            finally:
                if path:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
        provider = self._setting("voice_provider", "edge")
        if provider == "edge" and time.monotonic() < self._cloud_retry_after:
            return self._speak_windows(text, generation)
        limit = 190 if provider == "groq" else 210
        segments = split_speech(text, limit)
        if len(segments) > 1 or provider == "groq":
            return self._speak_segmented(segments, generation, provider)
        return self._speak_one_edge(text, generation)

    def _speak_one_edge(self, text, generation):
        if time.monotonic() >= self._cloud_retry_after:
            descriptor, path = tempfile.mkstemp(prefix="assistant-speech-", suffix=".mp3")
            os.close(descriptor)
            try:
                self._render_cloud(text, path, generation)
                if not self._speech_valid(generation):
                    raise _Cancelled()
                self._play_file(path, generation)
                return
            except _Cancelled:
                raise
            except Exception:
                self._cloud_retry_after = time.monotonic() + 60
                self._notice("Online voice is unavailable. Using the installed Windows voice.", cooldown=60)
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        if not self._speech_valid(generation):
            raise _Cancelled()
        self._speak_windows(text, generation)

    def _queue_rendered(self, rendered, item):
        while self._speech_valid(item[1]):
            try:
                rendered.put(item, timeout=0.1)
                return True
            except queue.Full:
                pass
        return False

    def _speak_segmented(self, segments, generation, provider):
        """Prefetch the next short segment while the current segment plays."""
        rendered = queue.Queue(maxsize=2)

        def produce():
            for index, segment in enumerate(segments):
                if not self._speech_valid(generation):
                    break
                path = None
                try:
                    use_groq = (provider == "groq" and self._setting("api_key", "")
                                and time.monotonic() >= self._groq_retry_after)
                    suffix = ".wav" if use_groq else ".mp3"
                    descriptor, path = tempfile.mkstemp(prefix="assistant-speech-", suffix=suffix)
                    os.close(descriptor)
                    if use_groq:
                        try:
                            self._render_groq(segment, path, generation)
                        except _Cancelled:
                            raise
                        except Exception:
                            self._groq_retry_after = time.monotonic() + 900
                            self._notice("Expressive Groq voice is unavailable. Using the natural Edge voice. Groq may require model terms acceptance.", cooldown=900)
                            try:
                                os.unlink(path)
                            except OSError:
                                pass
                            descriptor, path = tempfile.mkstemp(prefix="assistant-speech-", suffix=".mp3")
                            os.close(descriptor)
                            self._render_cloud(segment, path, generation)
                    else:
                        self._render_cloud(segment, path, generation)
                    if not self._speech_valid(generation):
                        raise _Cancelled()
                    if not self._queue_rendered(rendered, ("file", generation, index, path)):
                        raise _Cancelled()
                    path = None
                except _Cancelled:
                    break
                except Exception as error:
                    self._queue_rendered(rendered, ("error", generation, index, type(error).__name__))
                    break
                finally:
                    if path:
                        try:
                            os.unlink(path)
                        except OSError:
                            pass
            self._queue_rendered(rendered, ("done", generation, len(segments), None))

        producer = threading.Thread(target=produce, name="assistant-speech-prefetch", daemon=True)
        producer.start()
        try:
            while self._speech_valid(generation):
                try:
                    kind, token, index, value = rendered.get(timeout=0.1)
                except queue.Empty:
                    continue
                if token != generation or not self._speech_valid(generation):
                    if kind == "file":
                        try:
                            os.unlink(value)
                        except OSError:
                            pass
                    raise _Cancelled()
                if kind == "done":
                    return
                if kind == "error":
                    self._cloud_retry_after = time.monotonic() + 60
                    self._notice("Online voice is unavailable. Using the installed Windows voice.", cooldown=60)
                    self._speak_windows(" ".join(segments[index:]), generation)
                    return
                try:
                    self._play_file(value, generation)
                finally:
                    try:
                        os.unlink(value)
                    except OSError:
                        pass
        finally:
            producer.join(timeout=0.25)
            while True:
                try:
                    kind, _, _, value = rendered.get_nowait()
                except queue.Empty:
                    break
                if kind == "file":
                    try:
                        os.unlink(value)
                    except OSError:
                        pass

    def _render_groq(self, text, path, generation):
        if len(text) > 200:
            raise ValueError("Groq speech segments must be 200 characters or fewer")
        if not self._speech_valid(generation):
            raise _Cancelled()
        from groq import Groq
        default = "daniel" if self._setting("persona", "friday") == "alfred" else "diana"
        with Groq(api_key=self._setting("api_key"), timeout=15, max_retries=0) as client:
            response = client.audio.speech.create(
                model="canopylabs/orpheus-v1-english",
                voice=self._setting("groq_voice", default) or default,
                input=text,
                response_format="wav",
            )
            response.write_to_file(path)
        if not self._speech_valid(generation):
            raise _Cancelled()

    def _render_cloud(self, text, path, generation):
        import edge_tts

        async def render():
            default = "en-US-EmmaMultilingualNeural" if self._setting("persona", "friday") == "friday" else "en-GB-RyanNeural"
            communicate = edge_tts.Communicate(text, self._setting("voice", default) or default,
                                              rate="-2%", pitch="+0Hz", volume="+0%",
                                              connect_timeout=6, receive_timeout=12)
            task = asyncio.create_task(communicate.save(path))
            try:
                while not task.done():
                    if not self._speech_valid(generation):
                        raise _Cancelled()
                    await asyncio.sleep(0.05)
                await task
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        async def bounded():
            await asyncio.wait_for(render(), timeout=20)

        asyncio.run(bounded())

    def _play_file(self, path, generation):
        import pygame
        self._pygame = pygame
        if not self._speech_valid(generation):
            raise _Cancelled()
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        self._output_active.set()
        try:
            pygame.mixer.music.load(path)
            if not self._speech_valid(generation):
                raise _Cancelled()
            self._status("speaking", "Speaking…")
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if not self._speech_valid(generation):
                    raise _Cancelled()
                self._closed.wait(0.04)
        finally:
            try:
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
            finally:
                self._output_active.clear()

    def _speak_windows(self, text, generation):
        import pythoncom
        import win32com.client
        if not self._com_initialized:
            pythoncom.CoInitialize()
            self._com_initialized = True
        if self._sapi is None:
            self._sapi = win32com.client.Dispatch("SAPI.SpVoice")
        target_gender = "female" if self._setting("persona", "friday") == "friday" else "male"
        for voice in self._sapi.GetVoices():
            try:
                if voice.GetAttribute("Gender").lower() == target_gender:
                    self._sapi.Voice = voice
                    break
            except Exception:
                continue
        if not self._speech_valid(generation):
            raise _Cancelled()
        self._output_active.set()
        try:
            self._status("speaking", "Speaking with Windows voice…")
            self._sapi.Speak(text, 1)
            while not self._sapi.WaitUntilDone(50):
                if not self._speech_valid(generation):
                    raise _Cancelled()
        finally:
            try:
                self._sapi.Speak("", 3)
            finally:
                self._output_active.clear()
