"""Voice lifecycle regression tests. These never use live audio or a network."""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from assistant_core.voice import VoiceService, _Cancelled, _InterruptibleStream, split_speech, strip_wake_word, text_for_speech


def settings(**changes):
    values = dict(persona="friday", voice="en-GB-SoniaNeural", microphone_index=None,
                  speech_enabled=True, recognition_language="en-IN", stt_provider="google",
                  api_key="", followup_seconds=15)
    values.update(changes)
    return SimpleNamespace(**values)


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


class VoiceTests(unittest.TestCase):
    def service(self, **changes):
        service = VoiceService(settings(**changes), lambda *args, **kwargs: None)
        self.addCleanup(service.close)
        return service

    def test_inline_command_keeps_original_case_and_punctuation(self):
        self.assertEqual(strip_wake_word("Hey Friday, tell me about NASA?", "friday"),
                         (True, "tell me about NASA?"))
        self.assertEqual(strip_wake_word("Alfred what's the time", "alfred"),
                         (True, "what's the time"))
        self.assertEqual(strip_wake_word("fry day turn on the lights", "friday"),
                         (True, "turn on the lights"))

    def test_mentions_and_other_persona_are_not_wake_commands(self):
        self.assertEqual(strip_wake_word("The meeting is on Friday", "friday")[0], False)
        self.assertEqual(strip_wake_word("Friday what time is it", "alfred")[0], False)
        self.assertEqual(strip_wake_word("Friday", "friday"), (True, ""))

    def test_construction_and_start_do_not_listen_without_opt_in(self):
        service = self.service()
        self.assertFalse(service._started)
        self.assertFalse(service._wake_enabled)
        with patch.object(service, "_capture_and_transcribe") as capture:
            service.start(lambda text: None, lambda: False)
            time.sleep(0.15)
            capture.assert_not_called()

    def test_busy_covers_generation_and_playback_until_last_job(self):
        service = self.service()
        service.available = False
        entered = threading.Event()
        release = threading.Event()
        played = []

        def job(text, token):
            self.assertTrue(service.busy.is_set())
            entered.set()
            release.wait(1)
            played.append(text)

        with patch.object(service, "_speak_job", side_effect=job):
            service.start(lambda text: None, lambda: False)
            service.speak("First answer.")
            service.speak("Second answer.")
            self.assertTrue(entered.wait(1))
            self.assertTrue(service.busy.is_set())
            release.set()
            self.assertTrue(wait_for(lambda: len(played) == 2 and not service.busy.is_set()))
        self.assertEqual(played, ["First answer.", "Second answer."])

    def test_cancelled_generation_cannot_play_or_clear_new_busy_state(self):
        service = self.service()
        service.available = False
        entered = threading.Event()
        old_release = threading.Event()
        new_entered = threading.Event()
        new_release = threading.Event()
        played = []

        def job(text, token):
            if text == "old":
                entered.set()
                old_release.wait(1)
            else:
                new_entered.set()
                new_release.wait(1)
            if service._speech_valid(token):
                played.append(text)

        with patch.object(service, "_speak_job", side_effect=job):
            service.start(lambda text: None, lambda: False)
            service.speak("old")
            self.assertTrue(entered.wait(1))
            service.stop()
            service.speak("new")
            old_release.set()
            self.assertTrue(new_entered.wait(1))
            self.assertTrue(service.busy.is_set())
            self.assertEqual(played, [])
            new_release.set()
            self.assertTrue(wait_for(lambda: not service.busy.is_set()))
        self.assertEqual(played, ["new"])

    def test_playback_blocks_capture_after_cancellation(self):
        service = self.service()
        service._output_active.set()
        service.stop()
        self.assertFalse(service._capture_valid(service._capture_generation))
        service._output_active.clear()
        self.assertTrue(service._capture_valid(service._capture_generation))

    def test_wake_loop_dispatches_inline_question_without_second_recording(self):
        service = self.service()
        service.available = True
        delivered = threading.Event()
        received = []
        model_busy = threading.Event()

        def submit(text):
            received.append(text)
            model_busy.set()
            delivered.set()

        with patch.object(service, "_capture_and_transcribe", return_value="Friday, explain orbital mechanics") as capture:
            service.start(submit, model_busy.is_set)
            service.set_wake_enabled(True)
            self.assertTrue(delivered.wait(1))
            self.assertEqual(received, ["explain orbital mechanics"])
            self.assertEqual(capture.call_count, 1)

    def test_push_to_talk_waits_until_model_finishes(self):
        service = self.service()
        service.available = True
        model_busy = threading.Event()
        model_busy.set()
        delivered = threading.Event()
        received = []

        def submit(text):
            received.append(text)
            model_busy.set()
            delivered.set()

        with patch.object(service, "_capture_and_transcribe", return_value="What can you do?") as capture:
            service.start(submit, model_busy.is_set)
            service.listen_once()
            time.sleep(0.12)
            capture.assert_not_called()
            model_busy.clear()
            self.assertTrue(delivered.wait(1))
            self.assertEqual(received, ["What can you do?"])

    def test_interruptible_stream_stops_without_another_audio_read(self):
        calls = []
        stream = SimpleNamespace(read=lambda size: calls.append(size), close=lambda: None)
        wrapped = _InterruptibleStream(stream, lambda: False)
        with self.assertRaises(_Cancelled):
            wrapped.read(1024)
        self.assertEqual(calls, [])

    def test_speech_disabled_still_finishes_turn_for_followup(self):
        service = self.service(speech_enabled=False)
        service._conversation_active = True
        service._await_response_since = time.monotonic()
        service.speak("An answer shown as text.")
        self.assertFalse(service.busy.is_set())
        self.assertEqual(service._await_response_since, 0)
        self.assertGreater(service._followup_until, time.monotonic())

    def test_controller_cancelling_previous_turn_preserves_voice_followup(self):
        service = self.service(speech_enabled=False)
        service._conversation_active = True
        service.stop(preserve_conversation=True)
        self.assertTrue(service._conversation_active)
        self.assertGreater(service._await_response_since, 0)
        service.speak("Here's the answer.")
        self.assertGreater(service._followup_until, time.monotonic())
        service.stop()
        self.assertFalse(service._conversation_active)
        self.assertEqual(service._followup_until, 0)

    def test_speech_formatting_preserves_prose_and_hides_raw_code_urls(self):
        text = "## Answer\n**Use this:**\n```python\nprint('sample')\n```\nSource: [NASA](https://nasa.gov/a-very-long-link)."
        result = text_for_speech(text)
        self.assertIn("Use this:", result)
        self.assertIn("NASA", result)
        self.assertIn("code in the conversation", result)
        self.assertNotIn("https", result)
        self.assertNotIn("print(", result)
        self.assertNotIn("**", result)

    def test_long_answers_have_a_bounded_spoken_excerpt(self):
        result = text_for_speech("A fairly short sentence. " * 300)
        self.assertLess(len(result), 2500)
        self.assertTrue(result.endswith("The rest is in the conversation."))

    def test_speech_segments_preserve_all_text_and_bound_latency_units(self):
        original = "First short sentence. " + ("A longer clause with useful context, " * 14) + "finished. Last point!"
        pieces = split_speech(original, 190)
        self.assertGreater(len(pieces), 2)
        self.assertTrue(all(len(piece) <= 190 for piece in pieces))
        self.assertEqual(" ".join(pieces), " ".join(original.split()))

    def test_wake_detection_emits_overlay_event(self):
        events = []
        service = VoiceService(settings(), lambda kind, **payload: events.append((kind, payload)))
        self.addCleanup(service.close)
        service.available = True
        delivered = threading.Event()
        with patch.object(service, "_capture_and_transcribe", return_value="Friday, status report"):
            service.start(lambda text: delivered.set(), lambda: False)
            service.set_wake_enabled(True)
            self.assertTrue(delivered.wait(1))
        self.assertTrue(any(kind == "wake_detected" for kind, _ in events))

    def test_groq_segments_fall_back_to_edge_without_losing_order(self):
        service = self.service(api_key="configured", voice_provider="groq", groq_voice="diana")
        rendered = []
        played = []
        def edge(text, path, token):
            rendered.append(text)
            with open(path, "wb") as stream:
                stream.write(b"audio")
        with patch.object(service, "_render_groq", side_effect=OSError("terms required")), \
                patch.object(service, "_render_cloud", side_effect=edge), \
                patch.object(service, "_play_file", side_effect=lambda path, token: played.append(path)):
            service._speak_job("One useful sentence. A second useful sentence.", service._speech_generation)
        self.assertEqual(rendered, ["One useful sentence. A second useful sentence."])
        self.assertEqual(len(played), 1)

    def test_cloud_failure_uses_windows_and_removes_temporary_file(self):
        service = self.service()
        paths = []

        def render(text, path, token):
            paths.append(path)
            raise OSError("offline")

        with patch.object(service, "_render_cloud", side_effect=render), \
                patch.object(service, "_speak_windows") as fallback:
            service._speak_job("An answer", service._speech_generation)
            fallback.assert_called_once()
        import os
        self.assertEqual(len(paths), 1)
        self.assertFalse(os.path.exists(paths[0]))

    def test_cancelled_cloud_job_never_falls_back(self):
        service = self.service()
        with patch.object(service, "_render_cloud", side_effect=_Cancelled), \
                patch.object(service, "_speak_windows") as fallback:
            with self.assertRaises(_Cancelled):
                service._speak_job("Outdated answer", service._speech_generation)
            fallback.assert_not_called()

    def test_cancelled_prefetch_cleans_file_that_could_not_be_queued(self):
        service = self.service()
        generation = service._speech_generation
        rendered_paths = []
        fourth_rendered = threading.Event()
        release_playback = threading.Event()

        def render(_text, path, _token):
            rendered_paths.append(path)
            with open(path, "wb") as stream:
                stream.write(b"audio")
            if len(rendered_paths) == 4:
                fourth_rendered.set()

        def play(_path, _token):
            release_playback.wait(1)

        with patch.object(service, "_render_cloud", side_effect=render), \
                patch.object(service, "_play_file", side_effect=play):
            worker = threading.Thread(
                target=service._speak_segmented,
                args=(["one", "two", "three", "four"], generation, "edge"),
            )
            worker.start()
            self.assertTrue(fourth_rendered.wait(1))
            service.stop()
            release_playback.set()
            worker.join(1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(rendered_paths), 4)
        import os
        self.assertTrue(all(not os.path.exists(path) for path in rendered_paths))


if __name__ == "__main__":
    unittest.main()
