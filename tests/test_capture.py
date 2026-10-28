"""Real PCM regression tests without recording or network calls."""
import audioop
import io
import unittest
from types import SimpleNamespace
import speech_recognition as sr
from assistant_core.capture import listen, normalize


def pcm(level, seconds):
    return int(level).to_bytes(2, 'little', signed=True) * round(16000 * seconds)


def source(data):
    buffer = io.BytesIO(data)
    return SimpleNamespace(CHUNK=320, SAMPLE_RATE=16000, SAMPLE_WIDTH=2, stream=SimpleNamespace(read=lambda count: buffer.read(count * 2)))


class CaptureTests(unittest.TestCase):
    def test_loud_start_quiet_tail_and_natural_pause_preserved(self):
        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 300
        recognizer.pause_threshold = .95
        raw = pcm(100, .2) + pcm(8000, .5) + pcm(80, .7) + pcm(500, .8) + pcm(0, 1.1)
        device = source(raw)
        captured = listen(recognizer, device)
        self.assertIn(pcm(500, .8), captured.frame_data)
        self.assertTrue(captured.frame_data.startswith(pcm(100, .2)))
        self.assertLess(recognizer.energy_threshold, 300)
        self.assertGreater(len(captured.frame_data) / 32000, 3)

    def test_silence_times_out_without_yielding(self):
        with self.assertRaises(sr.WaitTimeoutError):
            listen(sr.Recognizer(), source(pcm(0, 2)), timeout=.5)

    def test_stream_and_buffered_are_identical(self):
        raw = pcm(1000, .5) + pcm(0, 1)
        a = listen(sr.Recognizer(), source(raw)).frame_data
        b = b''.join(p.frame_data for p in listen(sr.Recognizer(), source(raw), stream=True))
        self.assertEqual(a, b)

    def test_quiet_audio_lift_is_bounded_and_silence_unchanged(self):
        for level, expected in ((0, 0), (100, 100), (1000, 4000), (10000, 14000), (30000, 30000)):
            result = normalize(sr.AudioData(pcm(level, .5), 16000, 2))
            self.assertLessEqual(abs(audioop.max(result.frame_data, 2) - expected), 1)

    def test_stream_cancellation_propagates_without_returning_partial(self):
        device = source(b'')
        def cancelled(_):
            raise InterruptedError('cancel')
        device.stream = SimpleNamespace(read=cancelled)
        with self.assertRaises(InterruptedError):
            listen(sr.Recognizer(), device)

    def test_overaggressive_noise_filter_cannot_erase_quiet_speech(self):
        audio = sr.AudioData(pcm(500, .5), 16000, 2)
        result = normalize(audio, process=lambda raw:bytes(len(raw)))
        self.assertEqual(audioop.rms(result.frame_data, 2), 2000)
        filtered = normalize(audio, process=lambda raw:audioop.mul(raw, 2, .5))
        self.assertEqual(audioop.rms(filtered.frame_data, 2), 1000)

    def test_a_single_click_does_not_trigger_transcription(self):
        raw = pcm(0, .1) + pcm(9000, .02) + pcm(0, 1)
        with self.assertRaises(sr.WaitTimeoutError):
            listen(sr.Recognizer(), source(raw), timeout=.8)

    def test_manual_end_keeps_long_pauses_until_release(self):
        raw = pcm(2000, .2) + pcm(0, 1.8) + pcm(700, .2) + pcm(0, 3)
        device = source(raw)
        read = device.stream.read
        frames = []
        def observed(count):
            chunk = read(count)
            frames.append(chunk)
            return chunk
        device.stream.read = observed
        result = listen(sr.Recognizer(), device, finish=lambda:len(frames) >= 115)
        self.assertIn(pcm(700, .2), result.frame_data)
        self.assertEqual(len(result.frame_data), 115 * 640)

    def test_capture_limit_reports_review_boundary(self):
        limited = []
        listen(sr.Recognizer(), source(pcm(2000, 3)), phrase_time_limit=.2,
               finish=lambda:False, on_limit=lambda:limited.append(True))
        self.assertEqual(limited, [True])

    def test_recognition_preferences_reject_malformed_types(self):
        from assistant_core.settings import Settings
        for field in ('recognition_model', 'shortcut_behavior'):
            for value in (None, [], {}, 7, 'invalid'):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    Settings().updated({field:value})
