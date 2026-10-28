"""Bounded PCM phrase capture. No models, devices or network opened on import."""
import audioop
from collections import deque
import math


def listen(recognizer, source, timeout=7, phrase_time_limit=30, stream=False,
           finish=None, on_limit=None):
    """Adapt to idle noise only; never move the gate during a spoken phrase.

    Keep 400ms before the onset and tolerate the configured interior pause.
    Cancellation is supplied by the source's interruptible stream wrapper.
    """
    import speech_recognition as sr

    def chunks():
        period = source.CHUNK / source.SAMPLE_RATE
        preroll = deque(maxlen=max(1, math.ceil(.4 / period)))
        elapsed = 0.0
        onset = 0.0
        while True:
            if finish is not None and finish():
                raise sr.WaitTimeoutError('Recording ended before speech.')
            raw = source.stream.read(source.CHUNK)
            if not raw:
                raise sr.WaitTimeoutError('Microphone ended before speech.')
            elapsed += period
            preroll.append(raw)
            level = audioop.rms(raw, source.SAMPLE_WIDTH)
            if level > recognizer.energy_threshold:
                onset += period
                if onset >= .06:
                    break
                if elapsed >= timeout:
                    raise sr.WaitTimeoutError('No sustained speech heard.')
                continue
            onset = 0.0
            if elapsed >= timeout:
                raise sr.WaitTimeoutError('No speech heard.')
            if recognizer.dynamic_energy_threshold:
                damping = .15 ** period
                target = max(50, min(10000, level * 1.5))
                recognizer.energy_threshold = recognizer.energy_threshold * damping + target * (1 - damping)
        # A loud first word must not raise the gate and erase quieter words.
        threshold = recognizer.energy_threshold
        yield sr.AudioData(b''.join(preroll), source.SAMPLE_RATE, source.SAMPLE_WIDTH)
        silence = 0.0
        duration = elapsed if finish is not None else 0.0
        while duration < phrase_time_limit:
            if finish is not None and finish():
                return
            raw = source.stream.read(source.CHUNK)
            if not raw:
                break
            duration += period
            silence = silence + period if audioop.rms(raw, source.SAMPLE_WIDTH) <= threshold else 0.0
            yield sr.AudioData(raw, source.SAMPLE_RATE, source.SAMPLE_WIDTH)
            if finish is None and silence >= recognizer.pause_threshold:
                return
        if duration >= phrase_time_limit and on_limit is not None:
            on_limit()

    if stream:
        return chunks()
    return sr.AudioData(b''.join(part.frame_data for part in chunks()), source.SAMPLE_RATE, source.SAMPLE_WIDTH)


def normalize(audio, process=None):
    """Lift quiet speech at most fourfold, without clipping or amplifying silence."""
    import speech_recognition as sr
    raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
    if process is not None and raw:
        try:
            cleaned = process(raw)
            # Noise reduction happens after phrase detection. Reject output that
            # would erase most of a quiet laptop-microphone recording.
            if len(cleaned) == len(raw) and audioop.rms(cleaned, 2) >= audioop.rms(raw, 2) * .35:
                raw = cleaned
        except Exception:
            pass  # Keep the usable original if the optional processor fails.
    peak = audioop.max(raw, 2) if raw else 0
    if peak < 150 or peak >= 14000:
        return sr.AudioData(raw, 16000, 2)
    return sr.AudioData(audioop.mul(raw, 2, min(4.0, 14000 / peak)), 16000, 2)
