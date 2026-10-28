from pathlib import Path
from tempfile import TemporaryDirectory
import queue
import threading
import time
import unittest
from unittest.mock import Mock, patch

from assistant_core.brain import BrainError
from assistant_core.controller import AssistantController
from assistant_core.settings import Settings


class FakeVoice:
    def __init__(self, settings, emit):
        self.settings = settings
        self.busy = threading.Event()
        self.spoken = []
        self.preserve = []
        self.wake = False
    def start(self, callback, is_busy):
        self.callback = callback
    def speak(self, text, **kwargs):
        self.spoken.append(text)
    def stop(self, preserve_conversation=False):
        self.preserve.append(preserve_conversation)
    def listen_once(self, **kwargs):
        self.listen_options = kwargs
    def set_wake_enabled(self, enabled):
        self.wake = enabled
    def close(self):
        pass
    def update_settings(self, settings):
        self.settings = settings
    def list_microphones(self):
        return [(1, "Test input")]


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.patch = patch("assistant_core.controller.VoiceService", FakeVoice)
        self.patch.start()
        self.catalog_patch = patch("assistant_core.controller.ActionRouter._installed_apps", return_value=())
        self.catalog_patch.start()
        self.controller = AssistantController(Path(self.tmp.name), "friday")
        self.controller.start()

    def tearDown(self):
        self.controller.close()
        self.controller._worker.join(timeout=1)
        # Production logger handlers are persistent for a persona; release our test file.
        for handler in list(self.controller.log.handlers):
            handler.close()
            self.controller.log.removeHandler(handler)
        self.patch.stop()
        self.catalog_patch.stop()
        self.tmp.cleanup()

    def wait_done(self):
        until = time.monotonic() + 3
        while self.controller._busy.is_set() and time.monotonic() < until:
            time.sleep(0.01)
        self.assertFalse(self.controller._busy.is_set())

    def events(self):
        result = []
        while True:
            try:
                result.append(self.controller.events.get_nowait())
            except queue.Empty:
                return result

    def test_start_keeps_mic_off_and_does_not_speak(self):
        self.assertFalse(self.controller.voice.wake)
        self.assertEqual(self.controller.voice.spoken, [])

    def test_screen_request_uses_vision_and_does_not_save_answer(self):
        from dataclasses import replace
        self.controller.settings = replace(self.controller.settings, api_key='test')
        self.controller.brain.answer_screen = Mock(return_value='PRIVATE SCREEN ANSWER')
        with patch('assistant_core.automation_worker.isolated', return_value='data:image/jpeg;base64,test') as capture:
            self.controller.submit('look at my screen and explain the error')
            self.wait_done()
        capture.assert_called_once()
        self.controller.brain.answer_screen.assert_called_once()
        self.assertNotIn('PRIVATE SCREEN ANSWER', str(self.controller.memory.snapshot()))

    def test_screen_request_without_key_never_captures(self):
        from dataclasses import replace
        self.controller.settings = replace(self.controller.settings, api_key='')
        with patch('assistant_core.automation_worker.isolated') as capture:
            self.controller.submit('what is on my screen')
            self.wait_done()
        capture.assert_not_called()

    def test_direct_dictation_captures_only_after_binding_target(self):
        binding = {'field': {'mode': 'selection'}}
        with patch.object(self.controller.router.desktop, 'prepare_dictation', return_value=binding):
            self.controller.submit('dictate in Notepad')
            self.wait_done()
        self.assertTrue(self.controller.voice.listen_options['dictation'])
        with patch.object(self.controller, '_insert_dictation') as insert:
            self.controller.voice.listen_options['on_dictation']('shutdown computer')
        self.assertEqual(insert.call_args.args[:2], (binding, 'shutdown computer'))
        self.assertEqual(self.controller.voice.spoken, [])

    def test_explicit_app_text_stays_out_of_model_and_history(self):
        self.controller.brain.answer = Mock()
        with patch.object(self.controller.router.desktop, 'controls', return_value='PRIVATE DOCUMENT BODY') as read:
            self.controller.submit('read text in Notepad')
            self.wait_done()
        read.assert_called_once_with('Notepad', 'read')
        self.controller.brain.answer.assert_not_called()
        self.assertTrue(any(e.get('kind') == 'text_preview' and e.get('text') == 'PRIVATE DOCUMENT BODY' for e in self.events()))
        self.assertNotIn('PRIVATE DOCUMENT BODY', str(self.controller.memory.snapshot()))

    def test_cancelled_app_read_does_not_show_preview(self):
        def read(*args):
            self.controller._cancel.set()
            return 'STALE CONTENT'
        with patch.object(self.controller.router.desktop, 'controls', side_effect=read):
            self.controller.submit('read text in Notepad')
            self.wait_done()
        self.assertFalse(any(e.get('kind') == 'text_preview' for e in self.events()))

    def test_startup_setting_registers_and_persists(self):
        self.controller.startup = Mock()
        self.controller.save_settings({"start_with_windows": True})
        self.controller.startup.set_enabled.assert_called_once_with(True)
        self.assertTrue(Settings.load(self.tmp.name, "friday").start_with_windows)
        self.controller.save_settings({"start_with_windows": False})
        self.controller.startup.set_enabled.assert_called_with(False)
        self.assertFalse(Settings.load(self.tmp.name, "friday").start_with_windows)

    def test_startup_registry_failure_leaves_settings_unchanged(self):
        self.controller.startup = Mock()
        self.controller.startup.set_enabled.side_effect = PermissionError("denied")
        with self.assertRaises(PermissionError):
            self.controller.save_settings({"start_with_windows": True})
        self.assertFalse(self.controller.settings.start_with_windows)
        self.assertFalse((Path(self.tmp.name) / "settings.json").exists())

    def test_failed_settings_save_restores_previous_startup_command(self):
        for previous, enabled in ((None, True), ('"C:\\Old\\FRIDAY.exe" --background', False)):
            with self.subTest(enabled=enabled):
                self.controller.startup = Mock()
                self.controller.startup.get_command.return_value = previous
                with patch.object(Settings, "save", side_effect=OSError("disk full")):
                    with self.assertRaisesRegex(OSError, "disk full"):
                        self.controller.save_settings({"start_with_windows": enabled})
                self.controller.startup.restore.assert_called_once_with(previous)

    def test_startup_registration_is_authoritative_on_launch(self):
        Settings(start_with_windows=True).save(self.tmp.name)
        manager = Mock()
        manager.refresh.return_value = False
        replacement = AssistantController(self.tmp.name, "friday", startup=manager)
        try:
            self.assertFalse(replacement.settings.start_with_windows)
            manager.refresh.assert_called_once_with()
        finally:
            replacement.close()

    def test_wake_preference_persists_and_is_restored_on_start(self):
        self.controller.set_wake_enabled(True)
        self.assertTrue(self.controller.settings.wake_on_start)
        self.controller.close()
        replacement = AssistantController(Path(self.tmp.name), "friday")
        try:
            replacement.start()
            self.assertTrue(replacement.voice.wake)
        finally:
            replacement.close()
            replacement._worker.join(timeout=1)

    def test_local_command_answer_is_spoken_and_saved(self):
        self.controller.submit("Friday, what time is it?")
        self.wait_done()
        self.assertIn("It is", self.controller.voice.spoken[-1])
        history, _ = self.controller.memory.snapshot()
        self.assertEqual(history[0]["content"], "what time is it?")
        self.assertEqual(history[1]["role"], "assistant")

    def test_voice_request_preserves_followup(self):
        self.controller.voice.callback("what time is it?")
        self.wait_done()
        self.assertIn(True, self.controller.voice.preserve)

    def test_new_question_receives_previous_conversation(self):
        histories = []
        def answer(text, history, *args):
            histories.append(history)
            return "The robot is named Ember."
        with patch.object(self.controller.brain, "answer", side_effect=answer):
            self.controller.submit("My robot is named Ember")
            self.wait_done()
            self.controller.submit("What is its name?")
            self.wait_done()
        self.assertEqual(histories[0], [])
        self.assertEqual(histories[1][0]["content"], "My robot is named Ember")

    def test_cancelled_old_model_answer_never_speaks_or_saves(self):
        entered = threading.Event()
        release = threading.Event()
        def slow(*args):
            entered.set()
            release.wait(2)
            return "Obsolete answer"
        with patch.object(self.controller.brain, "answer", side_effect=slow):
            self.controller.submit("a question requiring the model")
            self.assertTrue(entered.wait(1))
            self.controller.stop()
            self.controller.submit("what time is it?")
            release.set()
            self.wait_done()
        self.assertNotIn("Obsolete answer", self.controller.voice.spoken)
        self.assertEqual(len(self.controller.memory.snapshot()[0]), 2)

    def test_new_request_keeps_old_actions_cancelled(self):
        entered, release = threading.Event(), threading.Event()
        observed = []
        def action(text):
            if text == 'long routine':
                entered.set()
                release.wait(2)
                observed.append(self.controller.router.cancelled())
            return 'Finished'
        with patch.object(self.controller, '_local_reply', side_effect=action):
            self.controller.submit('long routine')
            self.assertTrue(entered.wait(1))
            self.controller.submit('replacement request')
            release.set()
            self.wait_done()
        self.assertEqual(observed, [True])

    def test_model_errors_are_visible_and_not_saved_as_conversation(self):
        with patch.object(self.controller.brain, "answer", side_effect=BrainError("Update key in Settings")):
            self.controller.submit("explain stars")
            self.wait_done()
        self.assertTrue(any(event.get("text") == "Update key in Settings" for event in self.events()))
        self.assertEqual(self.controller.memory.snapshot()[0], [])

    def test_explicit_memory_can_be_cleared_separately(self):
        self.controller.submit("Remember that I like astronomy")
        self.wait_done()
        self.controller.clear_conversation()
        self.assertEqual(self.controller.memory.snapshot(), ([], ["I like astronomy"]))
        self.controller.clear_memories()
        self.assertEqual(self.controller.memory.snapshot(), ([], []))


if __name__ == "__main__":
    unittest.main()
