import asyncio
import base64
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from assistant_core.automation_worker import isolated
from assistant_core.device_watch import DeviceWatch
from assistant_core.maintenance import authenticate_update, prepare_install, recovery_status, restore_settings, version_tuple
from assistant_core.recognition import FinalTranscript, StreamingRecognition, RecognitionError
from assistant_core.settings import Settings
from assistant_core.voice import VoiceService
from release_fixture import signed_update


def delayed_action(started, destination):
    Path(started).write_text('started')
    time.sleep(1)
    Path(destination).write_text('must not happen')


def worker_answer(value):
    return value + 1


class V51Tests(unittest.TestCase):
    def test_wake_verification_waits_for_full_prefix_and_rejects_weekday_mention(self):
        from assistant_core.wake import LocalWake
        grammar, verifier = Mock(), Mock()
        grammar.AcceptWaveform.return_value = verifier.AcceptWaveform.return_value = False
        grammar.PartialResult.return_value = '{"partial":"hey friday [unk]"}'
        verifier.PartialResult.side_effect = ['{"partial":"hey"}', '{"partial":"hey friday what"}', '{"partial":"hey friday what"}']
        with patch('vosk.Model'), patch('vosk.KaldiRecognizer', side_effect=[grammar, verifier, grammar, verifier]):
            wake = LocalWake('friday')
        self.assertIsNone(wake.feed(bytes(640)))
        self.assertIsNone(wake.feed(bytes(640)))
        self.assertEqual(len(wake.feed(bytes(640))), 3)
        wake.reset()
        grammar.PartialResult.return_value = '{"partial":"friday"}'
        verifier.PartialResult.side_effect = None
        verifier.PartialResult.return_value = '{"partial":"we will meet on friday"}'
        for _ in range(5):
            self.assertIsNone(wake.feed(bytes(640)))

    def test_segment_prefetch_is_bounded_and_cancelled(self):
        from assistant_core.audio_io import stream_edge_segments
        sources = []
        valid = threading.Event()
        valid.set()
        def prepare(*args):
            source = Mock()
            sources.append(source)
            return source
        def playback(text, voice, active, pcm, started, *args, **kwargs):
            started()
            valid.clear()
            kwargs['prepared'].close()
        with patch('assistant_core.audio_io.EdgeAudio', side_effect=prepare), patch('assistant_core.audio_io.stream_edge', side_effect=playback):
            stream_edge_segments(['one', 'two', 'three'], 'voice', valid.is_set, Mock(), Mock(), threading.Event(), threading.Event())
        self.assertEqual(len(sources), 2)
        for source in sources:
            source.close.assert_called_once()

    def test_streaming_interim_never_becomes_final_and_segments_deduplicate(self):
        previews = []
        transcript = FinalTranscript(previews.append)
        def result(text, start=0, final=False):
            transcript.accept({'type':'Results', 'start':start, 'is_final':final,
                'channel':{'alternatives':[{'transcript':text}]}})
        result('shut down')
        self.assertEqual(transcript.text(), '')
        result('open', final=True)
        result('open', final=True)
        result('Notepad', start=1, final=True)
        self.assertEqual(transcript.text(), 'open Notepad')
        self.assertFalse(transcript.acknowledged)
        transcript.accept({'type':'Metadata'})
        self.assertTrue(transcript.acknowledged)

    def test_streaming_requires_key_and_does_not_start_network(self):
        with patch.object(StreamingRecognition, '_run') as run, self.assertRaises(RecognitionError):
            StreamingRecognition('', 'en-IN', .55, lambda:True, Mock())
        run.assert_not_called()

    def test_streaming_wait_cancels_promptly_and_rejects_unacknowledged_results(self):
        cancel = threading.Event()
        with patch.object(StreamingRecognition, '_run'):
            session = StreamingRecognition('test', 'en-IN', .55, lambda:not cancel.is_set(), Mock())
            timer = threading.Timer(.05, cancel.set)
            timer.start()
            start = time.monotonic()
            with self.assertRaises(RecognitionError):
                session.finish()
            self.assertLess(time.monotonic() - start, .5)
            session = StreamingRecognition('test', 'en-IN', .55, lambda:True, Mock())
            session.done.set()
            with self.assertRaises(RecognitionError):
                session.finish()

    def test_streaming_backpressure_aborts_instead_of_dropping_words(self):
        with patch.object(StreamingRecognition, '_run'):
            session = StreamingRecognition('test', 'en-IN', .55, lambda:True, Mock())
            for _ in range(500):
                session.feed(bytes(640))
            with self.assertRaises(RecognitionError):
                session.feed(bytes(640))
            self.assertTrue(session.cancelled.is_set())

    def test_provider_connection_uses_header_and_explicit_close(self):
        import aiohttp
        sent, connected = [], {}
        class Socket:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def send_bytes(self, data): sent.append(data)
            async def send_json(self, data): sent.append(data)
            async def close(self): pass
            def __aiter__(self): return self
            async def __anext__(self):
                while {'type':'CloseStream'} not in sent:
                    await asyncio.sleep(.01)
                if getattr(self, 'finished', False): raise StopAsyncIteration
                self.finished = True
                return type('Message', (), {'type':aiohttp.WSMsgType.TEXT, 'data':'{"type":"Metadata"}'})()
        class Session:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def ws_connect(self, url, **kwargs):
                connected.update(url=url, **kwargs)
                return Socket()
        with patch.object(StreamingRecognition, '_run'):
            stream = StreamingRecognition('test-key', 'en-IN', .55, lambda:True, Mock())
        stream.feed(bytes(640))
        stream.ending.set()
        with patch('aiohttp.ClientSession', Session):
            asyncio.run(stream._connect())
        self.assertEqual(connected['headers'], {'Authorization':'Token test-key'})
        self.assertNotIn('test-key', connected['url'])
        self.assertEqual(sent, [bytes(640), {'type':'CloseStream'}])
        self.assertTrue(stream.transcript.acknowledged)

    def test_keys_stay_out_of_json_and_diagnostics_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings().updated({'stt_provider':'deepgram', 'deepgram_api_key':'test-secret'})
            settings.save(folder)
            self.assertNotIn('test-secret', (Path(folder)/'settings.json').read_text())
            self.assertEqual(Settings.load(folder, 'friday').deepgram_api_key, 'test-secret')
            for value in ('key\nother=value', 'x'*513):
                with self.assertRaises(ValueError):
                    settings.updated({'deepgram_api_key':value})

    def test_uia_spawn_returns_and_cancellation_prevents_late_side_effect(self):
        self.assertEqual(isolated(worker_answer, (2,), lambda:False), 3)
        with tempfile.TemporaryDirectory() as folder:
            started, destination = Path(folder)/'started', Path(folder)/'late'
            cancel = lambda: started.exists()
            with self.assertRaisesRegex(ValueError, 'cancelled'):
                isolated(delayed_action, (str(started), str(destination)), cancel)
            time.sleep(1.1)
            self.assertFalse(destination.exists())

    def test_uia_timeout_terminates_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder)/'late'
            with self.assertRaisesRegex(ValueError, 'time'):
                isolated(delayed_action, (str(Path(folder)/'started'), str(destination)), lambda:False, timeout=.2)
            time.sleep(1.1)
            self.assertFalse(destination.exists())

    def test_signed_update_rejects_manifest_key_signature_digest_and_origin_changes(self):
        with signed_update() as update:
            authenticate_update(update)
            for field, value in [('digest','0'*64), ('version','v9.0.0'), ('name','ALFRED-Setup.exe'),
                    ('url','https://evil.invalid/setup.exe'), ('manifest',base64.b64encode(b'{}').decode()),
                    ('signature',base64.b64encode(b'bad').decode()), ('public_key',base64.b64encode(b'wrong').decode())]:
                with self.subTest(field=field), self.assertRaises(ValueError):
                    authenticate_update({**update, field:value})

    def test_prepare_update_rechecks_file_and_preserves_keys_and_settings(self):
        with tempfile.TemporaryDirectory() as folder, signed_update() as update:
            root = Path(folder)
            Settings(api_key='groq-test', deepgram_api_key='deepgram-test').save(root)
            (root/'updates').mkdir()
            path = root/'updates'/'setup.exe'
            path.write_bytes(b'installer bytes')
            prepare_install(path, update, root, '5.0.0')
            self.assertIn('not completed', recovery_status(root, '5.0.0'))
            Settings.load(root, 'friday').updated({'voice':'en-GB-RyanNeural'}).save(root)
            restored = restore_settings(root, 'friday')
            self.assertEqual(restored.api_key, 'groq-test')
            self.assertEqual(restored.deepgram_api_key, 'deepgram-test')
            self.assertEqual(restored.voice, Settings().voice)
            self.assertIn('completed', recovery_status(root, '5.1.0'))
            path.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                prepare_install(path, update, root, '5.0.0')

    def test_beta_can_upgrade_to_same_number_stable_but_never_downgrades(self):
        self.assertLess(version_tuple('5.1.0-beta.1'), version_tuple('v5.1.0'))
        self.assertGreater(version_tuple('5.1.0-beta.1'), version_tuple('v5.0.0'))

    def test_duplicate_resume_events_are_coalesced(self):
        callback = Mock()
        monitor = DeviceWatch(callback)
        monitor.dispatch_power(4)
        monitor.dispatch_power(18)
        monitor.dispatch_power(7)
        self.assertEqual([call.args[0] for call in callback.call_args_list], ['suspend', 'resume'])
        monitor.close()
        monitor.dispatch_power(4)
        self.assertEqual(callback.call_count, 2)

    def test_missing_local_wake_never_uploads_standby_audio(self):
        voice = VoiceService(Settings(), Mock())
        source = Mock()
        with patch('speech_recognition.Microphone') as mic, patch('speech_recognition.Recognizer') as recognizer, \
                patch.object(voice, '_listen_for_local_wake', return_value=False), patch.object(voice._closed, 'wait'):
            mic.return_value.__enter__.return_value = source
            self.assertEqual(voice._capture_and_transcribe(voice._capture_generation, False, False), '')
            recognizer.return_value.listen.assert_not_called()
            recognizer.return_value.recognize_google.assert_not_called()
        voice.close()


if __name__ == '__main__':
    unittest.main()
