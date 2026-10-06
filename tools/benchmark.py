"""Repeatable synthetic benchmark. Never records a microphone or performs PC actions.

Use --online to time two Edge voices without playing sound. Reports contain only
the generated test corpus, timings and process resource counters, never secrets.
"""
import argparse
import audioop
from array import array
import json
import math
import os
from pathlib import Path
import random
import sys
import tempfile
import threading
import time
from unittest.mock import patch
import wave


def synthesize(text, path):
    import win32com.client
    if not path.is_file():
        stream = win32com.client.Dispatch('SAPI.SpFileStream')
        voice = win32com.client.Dispatch('SAPI.SpVoice')
        stream.Open(str(path), 3)
        try:
            voice.AudioOutputStream = stream
            voice.Speak(text)
        finally:
            stream.Close()
    with wave.open(str(path), 'rb') as source:
        pcm = source.readframes(source.getnframes())
        width, channels, rate = source.getsampwidth(), source.getnchannels(), source.getframerate()
    if width != 2:
        pcm = audioop.lin2lin(pcm, width, 2)
    if channels == 2:
        pcm = audioop.tomono(pcm, 2, .5, .5)
    if rate != 16000:
        pcm, _ = audioop.ratecv(pcm, 2, 1, rate, 16000, None)
    return bytes(3200) + pcm + bytes(32000)


def noise(pcm, snr):
    if snr is None:
        return pcm
    rng = random.Random(51)
    amplitude = audioop.rms(pcm, 2) / (10 ** (snr/20))
    return array('h', (max(-32768, min(32767, round(sample + rng.gauss(0, amplitude))))
                       for sample in array('h', pcm))).tobytes()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-tree', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--online', action='store_true')
    parser.add_argument('--corpus', type=Path, help='Reuse generated WAV files for source-to-source comparisons')
    args = parser.parse_args()
    sys.path.insert(0, str(args.source_tree))
    from assistant_core import __version__
    from assistant_core.wake import LocalWake
    from assistant_core.audio_io import AcousticProcessor, AudioPipe, stream_edge
    import psutil
    process = psutil.Process()
    started, cpu_start = time.monotonic(), process.cpu_times()
    result = {'version':__version__, 'scope':'Synthetic SAPI speech, deterministic white noise; no real microphone, speaker or app actions.',
              'wake':[], 'voices':[]}
    corpus = [('friday', 'Friday open Notepad', True), ('friday', 'Hey Friday what time is it', True),
              ('friday', 'We will meet on Friday', False), ('friday', 'Open Spotify', False),
              ('alfred', 'Alfred open Notepad', True), ('alfred', 'Hey Alfred what time is it', True),
              ('alfred', 'Read the red book', False), ('alfred', 'Open Spotify', False)]
    with tempfile.TemporaryDirectory() as temporary:
        folder = args.corpus or Path(temporary)
        folder.mkdir(parents=True, exist_ok=True)
        pcm_files = [synthesize(text, folder/f'{index}.wav') for index, (_, text, _) in enumerate(corpus)]
        for persona in ('friday', 'alfred'):
            load_start = time.monotonic()
            detector = LocalWake(persona)
            result[persona+'_model_load_ms'] = round((time.monotonic()-load_start)*1000, 1)
            for index, (name, text, expected) in enumerate(corpus):
                if name != persona:
                    continue
                for snr in (None, 20, 10):
                    detector.reset()
                    pcm = noise(pcm_files[index], snr)
                    when = None
                    begin = time.monotonic()
                    for offset in range(0, len(pcm)-639, 640):
                        if detector.feed(pcm[offset:offset+640]) is not None:
                            when = (offset+640)/32
                            break
                    result['wake'].append({'persona':persona, 'text':text, 'snr_db':snr, 'expected':expected,
                        'detected':when is not None, 'audio_time_to_detection_ms':when,
                        'processing_ms':round((time.monotonic()-begin)*1000, 1)})
    processor = AcousticProcessor()
    begin = time.monotonic()
    for _ in range(1000):
        processor.playback(bytes(960))
        processor.capture(bytes(320))
    result['aec_ms_per_10ms_frame'] = round(time.monotonic()-begin, 3)
    delays = []
    for _ in range(10):
        cancelled = threading.Event()
        pipe = AudioPipe(lambda:not cancelled.is_set())
        finished = threading.Event()
        thread = threading.Thread(target=lambda:(pipe.read(100), finished.set()))
        thread.start()
        begin = time.monotonic()
        cancelled.set()
        finished.wait(1)
        thread.join(1)
        delays.append((time.monotonic()-begin)*1000)
    result['decoder_cancel_ms_max'] = round(max(delays), 1)
    if args.online:
        class Sink:
            def write(self, pcm): pass
            def stop_stream(self): pass
            def close(self): pass
        class SilentAudio:
            def open(self, **kwargs): return Sink()
            def terminate(self): pass
        for voice in ('en-US-EmmaMultilingualNeural', 'en-GB-RyanNeural'):
            begin = time.monotonic()
            first = []
            entry = {'voice':voice}
            try:
                with patch('pyaudio.PyAudio', SilentAudio):
                    stream_edge('Your assistant is ready. You can ask a question or open an application.', voice,
                        lambda:True, lambda pcm:None, lambda:first.append(time.monotonic()), threading.Event(), threading.Event())
                entry.update(first_decoded_pcm_ms=round((first[0]-begin)*1000,1), total_ms=round((time.monotonic()-begin)*1000,1))
            except Exception as error:
                entry['error'] = type(error).__name__
            result['voices'].append(entry)
    result['elapsed_seconds'] = round(time.monotonic()-started,1)
    cpu_end = process.cpu_times()
    result['cpu_seconds'] = round(cpu_end.user+cpu_end.system-cpu_start.user-cpu_start.system, 2)
    result['rss_mb'] = round(process.memory_info().rss/1024**2,1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({key:value for key,value in result.items() if key != 'wake'}, indent=2))
    print('Wake errors:', sum(item['expected'] != item['detected'] for item in result['wake']), '/', len(result['wake']))


if __name__ == '__main__':
    main()
