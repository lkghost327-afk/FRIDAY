import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock
from types import SimpleNamespace

from assistant_core.brain import Brain, BrainError, Cancelled
from assistant_core.memory import Memory
from assistant_core.settings import Settings


def reply(content=None, calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls))])


class ToolCall:
    id = "call1"
    def __init__(self, name="get_time", arguments="{}"):
        self.function = SimpleNamespace(name=name, arguments=arguments)
    def model_dump(self, **kwargs):
        return {"id": self.id, "type": "function", "function": vars(self.function)}


class BrainTests(unittest.TestCase):
    def setUp(self):
        self.brain = Brain(Settings(api_key="test"))
        self.client = Mock()
        self.client.models.list.return_value = SimpleNamespace(data=[SimpleNamespace(id="openai/gpt-oss-120b")])
        self.brain._client_instance = self.client
        self.router = Mock(tools=[{"type": "function"}])
        self.router.execute.return_value = "It is 10:30 AM."
        self.cancel = threading.Event()

    def answer(self):
        return self.brain.answer("time please", [], [], self.router, self.cancel, lambda *a, **kw: None)

    def test_discovers_available_model_instead_of_retired_model(self):
        self.assertEqual(self.brain.model(), "openai/gpt-oss-120b")
        self.brain.model()
        self.client.models.list.assert_called_once()

    def test_model_unavailable_gives_actionable_message(self):
        self.brain.settings = Settings(api_key="test", model="retired")
        with self.assertRaisesRegex(BrainError, "auto"):
            self.brain.model()

    def test_real_tool_result_is_in_model_context(self):
        self.client.chat.completions.create.side_effect = [reply(calls=[ToolCall()]), reply("10:30 AM, boss.")]
        self.assertEqual(self.answer(), "10:30 AM, boss.")
        self.router.execute.assert_called_once_with("get_time", {})
        messages = self.client.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual(messages[-1]["role"], "tool")
        self.assertEqual(messages[-1]["content"], "It is 10:30 AM.")

    def test_duplicate_action_never_runs_twice(self):
        self.client.chat.completions.create.side_effect = [reply(calls=[ToolCall()]), reply(calls=[ToolCall()]), reply("Done")]
        self.answer()
        self.assertEqual(self.router.execute.call_count, 1)

    def test_bad_json_is_not_executed(self):
        self.client.chat.completions.create.side_effect = [reply(calls=[ToolCall(arguments="[1]")]), reply("Please clarify")]
        self.answer()
        self.router.execute.assert_not_called()

    def test_auto_model_can_fall_back_on_rate_limit(self):
        self.client.models.list.return_value = SimpleNamespace(data=[SimpleNamespace(id=n) for n in
            ("openai/gpt-oss-120b", "openai/gpt-oss-20b")])
        limited = RuntimeError("rate limited")
        limited.status_code = 429
        self.client.chat.completions.create.side_effect = [limited, reply("Answer from available model")]
        self.assertEqual(self.answer(), "Answer from available model")
        self.assertEqual(self.brain.resolved_model, "openai/gpt-oss-20b")

    def test_cancel_after_model_prevents_tool_side_effect(self):
        def response(**kwargs):
            self.cancel.set()
            return reply(calls=[ToolCall()])
        self.client.chat.completions.create.side_effect = response
        with self.assertRaises(Cancelled):
            self.answer()
        self.router.execute.assert_not_called()

    def test_completed_action_remains_visible_if_summary_request_fails(self):
        self.client.chat.completions.create.side_effect = [reply(calls=[ToolCall()]), RuntimeError("provider unavailable")]
        self.assertIn("It is 10:30 AM.", self.answer())
        self.assertEqual(self.router.execute.call_count, 1)

    def test_empty_key_needs_no_client_and_local_app_can_start(self):
        with self.assertRaisesRegex(BrainError, "Settings"):
            Brain(Settings()).model()


class PersistenceTests(unittest.TestCase):
    def test_settings_preserve_other_env_entries_and_hide_key_from_json(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)
            (path / ".env").write_text("SPOTIPY_CLIENT_ID=preserved\nGROQ_API_KEY=old\n", encoding="utf-8")
            settings = Settings.load(path, "alfred").updated({"api_key": "private-test", "model": "auto"})
            settings.save(path)
            self.assertNotIn("private-test", (path / "settings.json").read_text())
            self.assertIn("SPOTIPY_CLIENT_ID=preserved", (path / ".env").read_text())
            self.assertEqual(Settings.load(path, "alfred").api_key, "private-test")
            self.assertEqual(settings.voice, "en-GB-RyanNeural")

    def test_settings_reject_invalid_input(self):
        for data in ({"microphone_index": -1}, {"followup_seconds": 900}, {"api_key": "bad\nKEY=bad"},
                     {"stt_provider": "madeup"}, {"speech_enabled": "yes"}, {"wake_on_start": "yes"},
                     {"voice_provider": "madeup"}, {"groq_voice": "madeup"}, {"voice": "madeup"}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                Settings().updated(data)

    def test_history_persists_complete_bounded_pairs(self):
        with TemporaryDirectory() as folder:
            memory = Memory(folder)
            for i in range(20):
                memory.add_turn(f"question {i}", f"answer {i}")
            restored = Memory(folder)
            self.assertEqual(len(restored.history), 24)
            self.assertEqual(restored.history[0]["role"], "user")
            self.assertEqual(restored.history[-1]["content"], "answer 19")

    def test_saved_facts_are_explicit_deduplicated_and_removable(self):
        with TemporaryDirectory() as folder:
            memory = Memory(folder)
            memory.remember("I like robotics")
            memory.remember("I like robotics")
            memory.add_turn("PC has 2GB free", "Temporary current reading")
            self.assertEqual(memory.facts, ["I like robotics"])
            memory.clear_history()
            self.assertEqual(Memory(folder).facts, ["I like robotics"])
            memory.forget("robotics")
            self.assertEqual(Memory(folder).facts, [])

    def test_corrupt_state_is_preserved(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "data" / "assistant_state.json"
            path.parent.mkdir()
            path.write_text("broken", encoding="utf-8")
            memory = Memory(folder)
            self.assertTrue(memory.warning)
            memory.add_turn("hi", "hello")
            self.assertEqual(path.read_text(), "broken")


if __name__ == "__main__":
    unittest.main()
