"""Streaming, device recovery, action verification, routines and update contracts."""
import hashlib
import io
import json
import os
import zipfile
from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from assistant_core.actions import ActionRouter, AppWindow, InstalledApp
from assistant_core.audio_io import AudioPipe, AcousticProcessor, PartialPlaybackError
from assistant_core.desktop import DesktopActions
from assistant_core.maintenance import check_update, download_update, version_tuple, install_wake
from assistant_core.metrics import Metrics
from assistant_core.routines import Routines
from assistant_core.settings import Settings
from assistant_core.voice import VoiceService


class UpgradeTests(unittest.TestCase):
    def test_search_verifies_edit_value_not_accessible_label(self):
        desktop = DesktopActions(Mock())
        field = Mock()
        field.window_text.return_value = 'Search'
        field.get_value.return_value = 'test query'
        target = NS(pid=-1, process_name='example.exe', hwnd=123)
        with patch.object(desktop, 'one', return_value=target), patch('pywinauto.Desktop') as automation:
            automation.return_value.window.return_value.wrapper_object.return_value.descendants.return_value = [field]
            self.assertIn('submitted', desktop.controls('Example', 'search', 'test query'))
            field.set_edit_text.assert_called_once_with('test query')
            field.type_keys.assert_called_once_with('{ENTER}')
            field.type_keys.reset_mock()
            field.get_value.return_value = 'unchanged'
            with self.assertRaises(ValueError):
                desktop.controls('Example', 'search', 'test query')
            field.type_keys.assert_not_called()

    def test_uia_refuses_assistant_or_system_windows(self):
        desktop = DesktopActions(Mock())
        for target in (NS(pid=os.getpid(), process_name='FRIDAY.exe'), NS(pid=-1, process_name='winlogon.exe')):
            with patch.object(desktop, 'one', return_value=target), self.assertRaises(ValueError):
                desktop.controls('target', 'button', 'OK')

    def test_corrupt_saved_routine_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'routines.json'
            path.write_text('{"work": [null]}', encoding='utf-8')
            router = Mock()
            with self.assertRaises(ValueError):
                Routines(path).handle('list routines', router)
            router.execute.assert_not_called()

    def test_wake_install_rejects_traversal_and_incomplete_archives(self):
        from assistant_core.wake import MODEL_NAME
        for filenames in ([MODEL_NAME+'/../../escape'], [MODEL_NAME+'/am/final.mdl']):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as archive:
                for name in filenames:
                    archive.writestr(name, b'model')
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=None)
            response.iter_content.return_value = [buffer.getvalue()]
            with tempfile.TemporaryDirectory() as folder:
                target = Path(folder)/MODEL_NAME
                with patch('assistant_core.wake.model_directory', return_value=target), patch('assistant_core.maintenance.requests.get', return_value=response):
                    with self.assertRaises(ValueError):
                        install_wake()
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_audio_pipe_delivers_before_generation_finishes(self):
        pipe = AudioPipe(lambda:True)
        received = []
        ready = threading.Event()
        reader = threading.Thread(target=lambda:(received.append(pipe.read(4096)),ready.set()))
        reader.start()
        pipe.write(b'first network packet')
        self.assertTrue(ready.wait(1))
        self.assertEqual(received, [b'first network packet'])
        self.assertFalse(pipe.finished)
        pipe.finish()
        reader.join(1)

    def test_audio_pipe_cancellation_wakes_reader(self):
        cancelled = threading.Event()
        pipe = AudioPipe(lambda:not cancelled.is_set())
        finished = threading.Event()
        reader = threading.Thread(target=lambda:(pipe.read(10),finished.set()))
        reader.start()
        cancelled.set()
        self.assertTrue(finished.wait(.5))
        reader.join(1)

    def test_audio_pipe_limits_memory_and_rewinds_header(self):
        pipe = AudioPipe(lambda:True)
        pipe.write(b'header')
        self.assertEqual(pipe.read(3), b'hea')
        self.assertTrue(pipe.seek(0, NS(name='START')))
        self.assertEqual(pipe.read(6), b'header')
        self.assertFalse(pipe.seek(100, NS(name='START')))
        with self.assertRaises(ValueError):
            pipe.write(bytes(2*1024*1024))

    def test_real_echo_processor_accepts_silent_frames(self):
        processor = AcousticProcessor()
        processor.playback(bytes(960))
        self.assertEqual(len(processor.capture(bytes(640))), 640)
        with self.assertRaises(ValueError):
            processor.capture(bytes(12))

    def test_streaming_voice_does_not_render_a_complete_file(self):
        voice = VoiceService(Settings(), Mock())
        with patch('assistant_core.audio_io.stream_edge') as stream, patch.object(voice, '_render_cloud') as old:
            voice._speak_job('Hello there.', voice._speech_generation)
            stream.assert_called_once()
            old.assert_not_called()
        voice.close()

    def test_partial_stream_failure_does_not_repeat_spoken_prefix(self):
        voice = VoiceService(Settings(), Mock())
        with patch('assistant_core.audio_io.stream_edge', side_effect=PartialPlaybackError()), patch.object(voice, '_speak_windows') as fallback:
            voice._speak_job('Partly spoken answer.', voice._speech_generation)
            fallback.assert_not_called()
        voice.close()

    def test_stable_microphone_identity_recovers_reordered_device(self):
        voice = VoiceService(Settings(microphone_index=3, microphone_name='USB microphone'), Mock())
        with patch.object(voice, 'list_microphones', return_value=[(7,'USB microphone'),(2,'Laptop')]):
            self.assertEqual(voice._microphone_device(), 7)
        voice._mic_cache = (0, [])
        with patch.object(voice, 'list_microphones', return_value=[(2,'Laptop')]):
            self.assertIsNone(voice._microphone_device())
        voice.close()

    def test_local_transcription_emits_partial_without_network(self):
        import speech_recognition as sr
        events = []
        voice = VoiceService(Settings(stt_provider='local'), lambda kind,**data:events.append((kind,data)))
        decoder = Mock()
        decoder.AcceptWaveform.return_value = False
        decoder.PartialResult.side_effect = [json.dumps({'partial':'open'}), json.dumps({'partial':'open notepad'})]
        decoder.FinalResult.return_value = json.dumps({'text':'open notepad'})
        source = NS(stream=Mock())
        with patch('speech_recognition.Microphone') as mic, patch('speech_recognition.Recognizer') as recognizer, patch.object(voice,'_command_decoder',return_value=decoder):
            mic.return_value.__enter__.return_value = source
            recognizer.return_value.listen.return_value = iter([sr.AudioData(bytes(640),16000,2)]*2)
            self.assertEqual(voice._capture_and_transcribe(voice._capture_generation,True,False),'open notepad')
            recognizer.return_value.recognize_google.assert_not_called()
            self.assertTrue(recognizer.return_value.listen.call_args.kwargs['stream'])
        self.assertEqual([d['text'] for k,d in events if k=='transcript_partial'],['open','open notepad'])
        voice.close()

    def test_interruption_preserves_correction_preroll(self):
        voice = VoiceService(Settings(), Mock())
        voice.busy.set()
        voice._output_active.set()
        voice._echo_active.set()
        voice._on_transcript = Mock()
        decoder = Mock()
        decoder.AcceptWaveform.return_value = False
        decoder.PartialResult.return_value = json.dumps({'partial':'no actually'})
        pcm = (3000).to_bytes(2,'little',signed=True)*320
        source = NS(stream=Mock())
        source.stream.read.return_value = pcm
        with patch('speech_recognition.Microphone') as mic, patch.object(voice,'_command_decoder',return_value=decoder), patch.object(voice,'_processor',return_value=Mock()), patch.object(voice,'_clean_capture',side_effect=lambda p:p):
            mic.return_value.__enter__.return_value = source
            voice._listen_for_interrupt()
        voice._on_transcript.assert_called_once_with('stop')
        self.assertTrue(voice._listen_request.is_set())
        self.assertEqual(voice._barge_frames,[pcm,pcm])
        voice.close()

    def test_reference_expires_instead_of_guessing(self):
        desktop = DesktopActions(Mock())
        with self.assertRaises(ValueError):
            desktop.resolve_reference('it')
        desktop.remember('Spotify')
        self.assertEqual(desktop.resolve_reference('it'),'Spotify')
        desktop.last_used -= 301
        with self.assertRaises(ValueError):
            desktop.resolve_reference('it')

    def test_verification_distinguishes_actual_window_state(self):
        router = NS(_stop=threading.Event(), cancelled=lambda:False)
        desktop = DesktopActions(router)
        with patch.object(desktop,'windows',side_effect=[[],[Mock()]]):
            self.assertIn('Confirmed',desktop.verify('Notepad',True,timeout=.5))
        with patch.object(desktop,'windows',return_value=[Mock()]):
            self.assertIn('still open',desktop.verify('Notepad',False,timeout=0))
        with patch.object(desktop,'windows',return_value=[]):
            self.assertIn('not confirmed',desktop.verify('Notepad',True,timeout=0))

    def test_routine_validates_all_steps_before_side_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            routines = Routines(Path(folder)/'routines.json')
            router = Mock()
            with self.assertRaises(ValueError):
                routines.handle('create routine work: open Notepad; shut down computer',router)
            router.execute.assert_not_called()
            self.assertFalse(routines.path.exists())

    def test_routine_persistence_order_and_cancel(self):
        with tempfile.TemporaryDirectory() as folder:
            routines = Routines(Path(folder)/'routines.json')
            router = NS(_stop=threading.Event(),cancelled=lambda:False,execute=Mock(return_value='Confirmed'))
            routines.handle('create routine work: open Notepad; volume 30',router)
            routines = Routines(routines.path)
            self.assertIn('work',routines.handle('list routines',router))
            routines.handle('start work',router)
            self.assertEqual([c.args[0] for c in router.execute.call_args_list],['open_app','set_volume'])
            router.execute.reset_mock()
            router.cancelled = lambda:True
            self.assertIn('cancelled',routines.handle('run routine work',router))
            router.execute.assert_not_called()

    def test_unconfirmed_routine_step_stops_next_action(self):
        with tempfile.TemporaryDirectory() as folder:
            routines = Routines(Path(folder)/'routines.json')
            router = NS(_stop=threading.Event(),cancelled=lambda:False,execute=Mock(return_value='Launch not confirmed'))
            routines.handle('create routine work: open Notepad; volume 30',router)
            self.assertIn('stopped',routines.handle('start work',router))
            self.assertEqual(router.execute.call_count,1)

    def test_metrics_are_bounded_and_first_audio_is_recorded_once(self):
        metrics = Metrics()
        metrics.begin()
        metrics.first_audio()
        metrics.first_audio()
        for value in range(150):
            metrics.record('latency',value)
        summary = metrics.summary()
        self.assertEqual(summary['request_to_audio_ms']['samples'],1)
        self.assertEqual(summary['latency']['samples'],100)

    def test_invalid_tuning_settings_are_rejected(self):
        for values in ({'wake_sensitivity':0},{'barge_in':'yes'},{'pause_seconds':float('nan')},{'echo_delay_ms':999}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Settings().updated(values)

    def test_update_rejects_wrong_origin_and_missing_digest(self):
        response = Mock(status_code=200)
        asset = {'name':'FRIDAY-Setup.exe','digest':'sha256:'+'1'*64,'size':123,'browser_download_url':'https://evil.invalid/setup.exe'}
        response.json.return_value = {'tag_name':'v9.0.0','assets':[asset]}
        with patch('assistant_core.maintenance.requests.get',return_value=response):
            with self.assertRaises(ValueError):
                check_update('friday','5.0.0')
            asset['browser_download_url']='https://github.com/lkghost327-afk/FRIDAY/releases/download/v9.0.0/FRIDAY-Setup.exe'
            asset['digest']=None
            with self.assertRaises(ValueError):
                check_update('friday','5.0.0')

    def test_update_download_verifies_and_removes_bad_partial(self):
        data=b'installer bytes'
        response=Mock()
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=None)
        response.iter_content.return_value=[data]
        update={'name':'FRIDAY-Setup.exe','size':len(data),'digest':'0'*64,'url':'https://github.com/example'}
        with tempfile.TemporaryDirectory() as folder, patch('assistant_core.maintenance.requests.get',return_value=response):
            with self.assertRaises(ValueError):
                download_update(update,folder)
            self.assertEqual(list(Path(folder).iterdir()),[])
            update['digest']=hashlib.sha256(data).hexdigest()
            self.assertEqual(download_update(update,folder).read_bytes(),data)


if __name__=='__main__':
    unittest.main()
