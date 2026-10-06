"""Incremental MP3 playback and synchronized WebRTC audio processing."""
import asyncio
import audioop
import threading
import time


class AudioPipe:
    """Seekable bounded sentence buffer; cancellation wakes a waiting decoder."""
    ffi_handle = None
    error_in_readcallback = None

    def __init__(self, valid):
        self.valid = valid
        self.data = bytearray()
        self.position = 0
        self.finished = False
        self.error = None
        self.condition = threading.Condition()

    def write(self, data):
        with self.condition:
            if len(self.data) + len(data) > 2 * 1024 * 1024:
                raise ValueError('Speech buffer limit exceeded')
            self.data.extend(data)
            self.condition.notify_all()

    def finish(self, error=None):
        with self.condition:
            self.finished, self.error = True, error
            self.condition.notify_all()

    def read(self, amount):
        with self.condition:
            while self.position >= len(self.data) and not self.finished and self.valid():
                self.condition.wait(.05)
            if not self.valid():
                return b''
            end = min(len(self.data), self.position + amount)
            result = bytes(self.data[self.position:end])
            self.position = end
            return result

    def seek(self, offset, origin):
        # MP3 decoder probing can rewind the already received header.
        name = getattr(origin, 'name', '')
        with self.condition:
            target = offset if name == 'START' else self.position + offset if name == 'CURRENT' else -1
            if 0 <= target <= len(self.data):
                self.position = target
                return True
        return False


class AcousticProcessor:
    """One lock serializes reverse/output and capture calls into WebRTC APM."""
    def __init__(self, delay_ms=60):
        from aec_audio_processing import AudioProcessor
        self.processor = AudioProcessor(enable_aec=True, enable_ns=True, enable_agc=False, enable_vad=True)
        self.processor.set_stream_format(16000, 1)
        self.processor.set_reverse_stream_format(16000, 1)
        self.processor.set_stream_delay(delay_ms)
        self.lock = threading.Lock()
        self._rate_state = None
        self._reverse = b''

    def playback(self, pcm):
        with self.lock:
            converted, self._rate_state = audioop.ratecv(pcm, 2, 1, 48000, 16000, self._rate_state)
            self._reverse += converted
            while len(self._reverse) >= 320:
                self.processor.process_reverse_stream(self._reverse[:320])
                self._reverse = self._reverse[320:]

    def capture(self, pcm):
        if len(pcm) % 320:
            raise ValueError('Capture must consist of 10ms mono PCM frames')
        with self.lock:
            return b''.join(self.processor.process_stream(pcm[i:i+320]) for i in range(0, len(pcm), 320))


class EdgeAudio:
    """One bounded, cancellable sentence. Can be prepared while another plays."""
    def __init__(self, text, voice, valid):
        self.text, self.voice, self.valid = text, voice, valid
        self.stop = threading.Event()
        self.loop = self.task = None
        self.pipe = AudioPipe(self.alive)
        self.worker = threading.Thread(target=self._network, name='streaming-tts', daemon=True)
        self.worker.start()

    def alive(self):
        return self.valid() and not self.stop.is_set()

    def close(self):
        self.stop.set()
        self.pipe.finish()
        if self.loop is not None and self.task is not None:
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:
                pass

    async def _produce(self):
        import edge_tts
        self.loop, self.task = asyncio.get_running_loop(), asyncio.current_task()
        try:
            if not self.alive():
                return
            client = edge_tts.Communicate(self.text, self.voice, rate='-2%', connect_timeout=6, receive_timeout=10)
            async for chunk in client.stream():
                if not self.alive():
                    break
                if chunk['type'] == 'audio':
                    self.pipe.write(chunk['data'])
            self.pipe.finish()
        except asyncio.CancelledError:
            self.pipe.finish()
        except Exception as error:
            self.pipe.finish(error)

    def _network(self):
        asyncio.run(self._produce())


def stream_edge(text, voice, valid, on_pcm, on_start, output_active, echo_active, prepared=None):
    """Decode/play received MP3 chunks while Edge is still generating the rest."""
    import miniaudio
    import pyaudio
    source = prepared or EdgeAudio(text, voice, valid)
    pipe, alive = source.pipe, source.alive

    audio = None
    output = None
    decoder = None
    played = False
    try:
        decoder = miniaudio.stream_any(pipe, source_format=miniaudio.FileFormat.MP3,
                                      output_format=miniaudio.SampleFormat.SIGNED16,
                                      nchannels=1, sample_rate=48000, frames_to_read=480)
        audio = pyaudio.PyAudio()
        output = audio.open(format=pyaudio.paInt16, channels=1, rate=48000, output=True, frames_per_buffer=480)
        for samples in decoder:
            if not alive():
                break
            pcm = samples.tobytes()
            if not pcm:
                continue
            on_pcm(pcm)
            output_active.set()
            echo_active.set()
            if not played:
                on_start()
                played = True
            output.write(pcm)
        if pipe.error:
            raise pipe.error
        if not played and valid():
            raise OSError('No speech audio received')
        return played
    except Exception as error:
        # Never repeat an already spoken prefix after a mid-stream failure.
        if played:
            raise PartialPlaybackError('Speech stream interrupted') from error
        raise
    finally:
        source.close()
        for resource, method in ((decoder, 'close'), (output, 'stop_stream'), (output, 'close'), (audio, 'terminate')):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except Exception:
                    pass
        echo_active.clear()
        output_active.clear()


def stream_edge_segments(segments, voice, valid, on_pcm, on_start, output_active, echo_active):
    """Start the next sentence after first audio, eliminating repeated network gaps."""
    pending = {}
    played = False
    try:
        for index, text in enumerate(segments):
            if not valid():
                return
            source = pending.pop(index, None) or EdgeAudio(text, voice, valid)
            def started():
                nonlocal played
                played = True
                on_start()
                if index + 1 < len(segments) and valid():
                    pending[index+1] = EdgeAudio(segments[index+1], voice, valid)
            stream_edge(text, voice, valid, on_pcm, started, output_active, echo_active, prepared=source)
    except Exception as error:
        if played:
            raise PartialPlaybackError('Speech stream interrupted') from error
        raise
    finally:
        for source in pending.values():
            source.close()


class PartialPlaybackError(OSError):
    pass
