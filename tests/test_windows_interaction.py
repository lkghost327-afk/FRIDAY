"""Independent Windows equivalents: bounded commands, local context, literal dictation."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import threading
import unittest
from unittest.mock import Mock

from assistant_core.app_text import accessible_text
from assistant_core.hotkey import VoiceHotkey
from assistant_core.routines import Routines
from assistant_core.settings import Settings
from assistant_core.voice import VoiceService


class BehaviorTests(unittest.TestCase):
    def router(self, *results):
        return NS(_stop=threading.Event(), cancelled=lambda: False, execute=Mock(side_effect=results))

    def test_direct_chain_validates_all_steps_before_opening(self):
        with TemporaryDirectory() as folder:
            routines = Routines(Path(folder) / 'routines.json')
            router = self.router()
            for command in ('open Notepad then shutdown computer', 'open Notepad; volume 101',
                            'open Notepad then focus it', ';'.join(['open Notepad'] * 9)):
                with self.subTest(command=command), self.assertRaises(ValueError):
                    routines.handle(command, router)
            router.execute.assert_not_called()

    def test_natural_shortcut_saves_without_execution_and_runs_in_order(self):
        with TemporaryDirectory() as folder:
            routines = Routines(Path(folder) / 'routines.json')
            router = self.router('Confirmed: Notepad is open.', 'Volume is 30%.')
            routines.handle('when I say work, open Notepad then volume 30', router)
            router.execute.assert_not_called()
            routines.handle('work', router)
            self.assertEqual([call.args[0] for call in router.execute.call_args_list], ['open_app', 'set_volume'])

    def test_unrelated_phrase_does_not_replay_a_saved_routine(self):
        with TemporaryDirectory() as folder:
            routines = Routines(Path(folder) / 'routines.json')
            router = self.router()
            routines.handle('when I say work, open Notepad', router)
            self.assertIsNone(routines.handle('tell me about work', router))
            router.execute.assert_not_called()

    def test_device_level_mismatch_stops_remaining_steps(self):
        with TemporaryDirectory() as folder:
            routines = Routines(Path(folder) / 'routines.json')
            for command, response in [('volume 30 then open Notepad', 'Volume is 45%.'),
                                      ('brightness 30 then open Notepad', 'Display brightness: 30%, 50%.')]:
                router = self.router(response)
                self.assertIn('stopped', routines.handle(command, router))
                self.assertEqual(router.execute.call_count, 1)

    def test_confirmed_multi_display_level_continues(self):
        with TemporaryDirectory() as folder:
            router = self.router('Display brightness: 30%, 30%.', 'Confirmed: Notepad is open.')
            result = Routines(Path(folder) / 'routines.json').handle('brightness 30 then open Notepad', router)
            self.assertNotIn('stopped', result)
            self.assertEqual(router.execute.call_count, 2)

    def test_missing_dependency_and_unknown_results_stop_chain(self):
        with TemporaryDirectory() as folder:
            routines = Routines(Path(folder) / 'routines.json')
            for result in ('This feature needs pycaw.', 'Requested.', 'not confirmed', ''):
                router = self.router(result)
                self.assertIn('stopped', routines.handle('open Notepad then volume 30', router))
                self.assertEqual(router.execute.call_count, 1)

    def test_cancel_after_first_step_never_runs_second(self):
        with TemporaryDirectory() as folder:
            router = self.router()
            def execute(*args):
                router._stop.set()
                return 'Confirmed: Notepad is open.'
            router.execute.side_effect = execute
            result = Routines(Path(folder) / 'routines.json').handle('open Notepad then volume 30', router)
            self.assertIn('cancelled', result)
            self.assertEqual(router.execute.call_count, 1)

    def test_app_text_excludes_private_subtrees_and_form_values(self):
        def node(name, kind='Text', private=False, children=()):
            return NS(element_info=NS(name=name, control_type=kind, element=NS(CurrentIsPassword=private)),
                      is_visible=lambda: True, children=lambda: list(children))
        window = node('', 'Window', children=[node('Hello'), node('Hello'),
                      node('secret', private=True, children=[node('nested-secret')]),
                      node('form-value', 'Edit'), node('x' * 9000)])
        text = accessible_text(window, limit=100)
        self.assertEqual(text.count('Hello'), 1)
        self.assertNotIn('secret', text)
        self.assertNotIn('form-value', text)
        self.assertLess(len(text), 180)

    def test_dictation_is_literal_and_cancelled_results_are_dropped(self):
        events = []
        voice = VoiceService(Settings(), lambda kind, **data: events.append((kind, data)))
        voice._on_transcript = Mock()
        try:
            token = voice._capture_generation
            words = 'Friday shutdown my computer. नमस्ते दुनिया।'
            voice._deliver_dictation(words, token)
            self.assertEqual(events[0], ('text_preview', {'title': 'Dictation — review and copy', 'text': words}))
            voice._on_transcript.assert_not_called()
            voice.stop()
            events.clear()
            voice._deliver_dictation(words, token)
            self.assertEqual(events, [])
        finally:
            voice.close()

    def test_hotkey_conflict_does_not_unregister_someone_elses_key(self):
        emit, api = Mock(), Mock()
        api.RegisterHotKey.return_value = 0
        VoiceHotkey('friday', emit)._run(api)
        self.assertEqual(emit.call_count, 2)
        api.UnregisterHotKey.assert_not_called()

    def test_global_escape_emits_cancel_only_while_armed(self):
        api = Mock()
        api.RegisterHotKey.return_value = 1
        api.PeekMessageW.return_value = 0
        api.GetAsyncKeyState.return_value = 0x8000
        events = []
        service = VoiceHotkey('friday', lambda kind, **data: (events.append(kind), service._stop.set()))
        service.cancel_enabled.set()
        service._run(api)
        self.assertEqual(events, ['voice_cancel'])
        api.GetAsyncKeyState.assert_called_once_with(0x1B)
        self.assertEqual(api.UnregisterHotKey.call_count, 2)

    def test_hotkey_unregisters_even_if_message_loop_fails(self):
        api = Mock()
        api.RegisterHotKey.return_value = 1
        api.PeekMessageW.side_effect = RuntimeError('test failure')
        with self.assertRaises(RuntimeError):
            VoiceHotkey('alfred', Mock())._run(api)
        self.assertEqual(api.RegisterHotKey.call_count, 2)
        api.RegisterHotKey.assert_any_call(None, 1, 0x4003, ord('A'))
        api.RegisterHotKey.assert_any_call(None, 2, 0x4007, ord('A'))
        self.assertEqual(api.UnregisterHotKey.call_count, 2)

    def test_shortcut_setting_is_opt_in_and_strictly_boolean(self):
        self.assertFalse(Settings().global_voice_shortcut)
        with self.assertRaises(ValueError):
            Settings().updated({'global_voice_shortcut': 'yes'})
