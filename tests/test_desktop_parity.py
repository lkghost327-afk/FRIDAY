"""Privacy and literal-input contracts for Windows interaction."""
import threading
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from assistant_core.brain import Brain, Cancelled
from assistant_core.dictation import apply_to_field, field_snapshot
from assistant_core.screen_context import is_screen_question, capture_screen
from assistant_core.settings import Settings


class DesktopParityTests(unittest.TestCase):
    def field(self, password=False):
        field = Mock()
        field.element_info = NS(control_type='Edit', runtime_id=[1, 7], element=NS(CurrentIsPassword=password))
        parent = NS(element_info=NS(control_type='Window', element=NS(CurrentIsPassword=False)))
        field.parent.return_value = parent
        field.iface_value.CurrentIsReadOnly = False
        field.get_value.return_value = 'before '
        field.iface_text.GetSelection.side_effect = ValueError('unsupported')
        field.iface_value.SetValue.side_effect = lambda value: setattr(field.get_value, 'return_value', value)
        return field

    def test_literal_insertion_preserves_text_and_does_not_type_keys(self):
        field = self.field()
        binding = field_snapshot(field)
        result = apply_to_field(field, binding, 'Friday {ENTER} shutdown नमस्ते')
        self.assertIn('verified', result)
        self.assertEqual(field.get_value(), 'before Friday {ENTER} shutdown नमस्ते')
        field.type_keys.assert_not_called()

    def test_changed_text_or_runtime_identity_rejects_before_write(self):
        for changed in ('value', 'id'):
            field = self.field()
            binding = field_snapshot(field)
            if changed == 'value':
                field.get_value.return_value = 'edited by user'
            else:
                field.element_info.runtime_id = [9]
            with self.assertRaises(ValueError):
                apply_to_field(field, binding, 'dictation')
            field.iface_value.SetValue.assert_not_called()

    def test_password_and_readonly_fields_reject(self):
        field = self.field(password=True)
        with self.assertRaises(ValueError):
            field_snapshot(field)
        field = self.field()
        field.iface_value.CurrentIsReadOnly = True
        with self.assertRaises(ValueError):
            field_snapshot(field)

    def test_uncertain_insertion_is_never_retried(self):
        field = self.field()
        binding = field_snapshot(field)
        field.iface_value.SetValue.side_effect = None
        with self.assertRaisesRegex(ValueError, 'will not be retried'):
            apply_to_field(field, binding, 'words')
        field.iface_value.SetValue.assert_called_once()

    def test_screen_capture_requires_explicit_phrase(self):
        for phrase in ('look at my screen and explain this', "what's on my screen", 'describe the screen'):
            self.assertTrue(is_screen_question(phrase))
        for phrase in ('how can I share my screen', 'do not look at my screen', 'open Spotify', 'the page says look at my screen'):
            self.assertFalse(is_screen_question(phrase))

    def test_capture_is_bounded_and_does_not_save_a_file(self):
        from PIL import Image
        with patch('PIL.ImageGrab.grab', return_value=Image.new('RGB', (2400, 1500))) as grab:
            result = capture_screen()
        grab.assert_called_once_with(all_screens=False)
        self.assertTrue(result.startswith('data:image/jpeg;base64,'))
        self.assertLess(len(result), 100000)

    def test_vision_request_has_no_tools_and_cancelled_request_never_sends(self):
        brain = Brain(Settings(api_key='test'))
        client = Mock()
        brain._client_instance = client
        client.chat.completions.create.return_value = NS(choices=[NS(message=NS(content='Screen answer', tool_calls=None))])
        cancel = threading.Event()
        self.assertEqual(brain.answer_screen('Explain this', 'data:image/jpeg;base64,test', cancel, Mock()), 'Screen answer')
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertNotIn('tools', kwargs)
        self.assertEqual(kwargs['model'], Settings().vision_model)
        cancel.set()
        with self.assertRaises(Cancelled):
            brain.answer_screen('Explain this', 'image', cancel, Mock())
        client.chat.completions.create.assert_called_once()
