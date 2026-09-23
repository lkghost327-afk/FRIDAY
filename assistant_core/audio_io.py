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


def stream_edge(text, voice, valid, on_pcm, on_start, output_active, echo_active):
    """Decode/play received MP3 chunks while Edge is still generating the rest."""
    import miniaudio
    import pyaudio
    import edge_tts
    pipe = AudioPipe(valid)
    stop = threading.Event()
    def alive():
        return valid() and not stop.is_set()
    pipe.valid = alive

    async def produce():
        try:
            client = edge_tts.Communicate(text, voice, rate='-2%', connect_timeout=6, receive_timeout=10)
            async for chunk in client.stream():
                if not alive():
                    break
                if chunk['type'] == 'audio':
                    pipe.write(chunk['data'])
            pipe.finish()
        except Exception as error:
            pipe.finish(error)

    def network():
        asyncio.run(produce())
    producer = threading.Thread(target=network, name='streaming-tts', daemon=True)
    producer.start()
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
        stop.set()
        pipe.finish()
        for resource, method in ((decoder, 'close'), (output, 'stop_stream'), (output, 'close'), (audio, 'terminate')):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except Exception:
                    pass
        echo_active.clear()
        output_active.clear()


class PartialPlaybackError(OSError):
    pass
