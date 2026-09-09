import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from assistant_core.actions import ActionRouter, AppWindow, InstalledApp
from assistant_core.brain import Brain, Cancelled
from assistant_core.lifecycle import SingleInstance
from assistant_core.power import PowerControl
from assistant_core.settings import Settings
from assistant_core.streaming import ReplySpeech
from assistant_core.voice import VoiceService
from assistant_core.wake import ReplayStream


def chunk(text=None, calls=None):
    return NS(choices=[NS(delta=NS(content=text, tool_calls=calls))])


class ImprovementsTests(unittest.TestCase):
    def test_stream_speaks_first_sentence_before_model_finishes(self):
        spoken = []
        speech = ReplySpeech(spoken.append)
        def response():
            yield chunk("First sentence. ")
            self.assertEqual(spoken, ["First sentence."])
            yield chunk("Here is the rest.")
        message = Brain._read_response(response(), threading.Event(), lambda kind, **data: speech.feed(data["text"]))
        speech.finish()
        self.assertEqual(message.content, "First sentence. Here is the rest.")
        self.assertEqual(spoken, ["First sentence.", "Here is the rest."])

    def test_stream_reconstructs_fragmented_tool_calls_without_spoken_arguments(self):
        events = []
        stream = iter([
            chunk(calls=[NS(index=0, id="id1", function=NS(name="open_app", arguments='{"app":'))]),
            chunk(calls=[NS(index=0, id=None, function=NS(name=None, arguments='"Spotify"}'))]),
        ])
        message = Brain._read_response(stream, threading.Event(), lambda kind, **data: events.append(kind))
        self.assertEqual(events, ["speech_reset"])
        self.assertEqual(message.tool_calls[0].function.arguments, '{"app":"Spotify"}')
        self.assertEqual(message.tool_calls[0].model_dump()["id"], "id1")

    def test_stream_cancellation_closes_response_and_stops_audio(self):
        cancelled = threading.Event()
        cancelled.set()
        stream = Mock()
        stream.__iter__ = Mock(return_value=iter([chunk("old")]))
        events = []
        with self.assertRaises(Cancelled):
            Brain._read_response(stream, cancelled, lambda kind, **data: events.append(kind))
        stream.close.assert_called_once()
        self.assertEqual(events, ["speech_reset"])

    def test_streamed_code_and_long_answers_are_bounded(self):
        spoken = []
        speech = ReplySpeech(spoken.append)
        for text in ["Here is code. ", "```python\nprint('secret code')\n", "```\n", "Some detail. " * 200]:
            speech.feed(text)
        speech.finish()
        result = " ".join(spoken)
        self.assertNotIn("print", result)
        self.assertEqual(result.count("The rest is in the conversation."), 1)
        self.assertLess(len(result), 1600)

    def test_store_spotify_launch_and_unique_short_names(self):
        with tempfile.TemporaryDirectory() as folder:
            router = ActionRouter(Path(folder), "friday", Mock())
            try:
                apps = (InstalledApp("Spotify", "shell_app", "Spotify.Package!App", ("spotify",), "start"),
                        InstalledApp("Microsoft Word", "shell_app", "Word!App", ("winword",), "start"))
                with patch.object(router, "_installed_apps", return_value=apps), patch.object(router, "_find_executable", return_value=None), patch.object(router, "_launch_installed_app") as launch:
                    self.assertIn("Spotify", router.handle("open Spotify"))
                    self.assertEqual(launch.call_args.args[0], apps[0])
                    self.assertIn("Microsoft Word", router.handle("open Word"))
                    self.assertEqual(launch.call_args.args[0], apps[1])
            finally:
                router.close()

    def test_power_request_parsing_is_explicit_and_cancel_works(self):
        with tempfile.TemporaryDirectory() as folder:
            router = ActionRouter(Path(folder), "friday", Mock())
            try:
                with patch.object(router.power, "request", return_value="countdown") as request:
                    for command, action in [("shut down my computer", "shutdown"), ("put my device to sleep", "sleep"), ("restart my laptop", "restart"), ("lock my screen", "lock")]:
                        self.assertEqual(router.handle(command), "countdown")
                        request.assert_called_with(action)
                    self.assertIsNone(router.handle("How do I shut down my computer?"))
                with patch("assistant_core.power.threading.Thread") as thread, patch.object(router.power, "_perform") as perform:
                    self.assertIn("10 seconds", router.handle("shutdown"))
                    target = thread.call_args.kwargs["target"]
                    self.assertIn("Cancelled", router.handle("cancel shutdown"))
                    target()
                    perform.assert_not_called()
            finally:
                router.close()

    def test_store_whatsapp_root_window_matches_its_app_name(self):
        with tempfile.TemporaryDirectory() as folder:
            router = ActionRouter(Path(folder), "friday", Mock())
            try:
                app = InstalledApp("WhatsApp", "shell_app", "WhatsApp.Package!App", ("whatsapp",), "start")
                window = AppWindow(101, 999999, "WhatsApp", "WhatsApp.Root.exe")
                with patch.object(router, "_installed_apps", return_value=(app,)), patch.object(router, "_user_windows", return_value=[window]), patch.object(router, "_post_window_close", return_value=True) as close:
                    self.assertIn("close normally", router.handle("close WhatsApp"))
                    close.assert_called_once_with(101)
            finally:
                router.close()

    def test_shutdown_does_not_force_unsaved_apps_closed(self):
        with patch("assistant_core.power.subprocess.run") as run:
            PowerControl._perform("shutdown")
            arguments = run.call_args.args[0]
            self.assertEqual(arguments[1:], ["/s", "/t", "0"])
            self.assertNotIn("/f", arguments)

    def test_failed_online_voice_does_not_retry_for_every_long_sentence(self):
        voice = VoiceService(Settings(), Mock())
        voice._cloud_retry_after = time.monotonic() + 30
        text = "Long offline reply. " * 40
        with patch.object(voice, "_render_cloud") as cloud, patch.object(voice, "_speak_windows") as local:
            voice._speak_job(text, voice._speech_generation)
            cloud.assert_not_called()
            local.assert_called_once_with(text, voice._speech_generation)
        voice.close()

    def test_hidden_main_window_does_not_draw_or_poll_telemetry(self):
        from assistant_core.ui import AssistantWindow
        window = NS(_hidden_to_tray=True, _schedule=Mock(), core_canvas=Mock(),
                    _animate=Mock(), _update_telemetry=Mock())
        with patch("assistant_core.ui.psutil") as stats:
            AssistantWindow._animate(window)
            AssistantWindow._update_telemetry(window)
            stats.cpu_percent.assert_not_called()
        window.core_canvas.delete.assert_not_called()
        self.assertEqual(window._schedule.call_count, 2)

    def test_cancellation_discards_queued_text_and_audio_preparations(self):
        voice = VoiceService(Settings(), Mock())
        voice.speak("First old reply.", prefetch=True)
        voice.speak("Second old reply.", prefetch=True)
        futures = [future for group in voice._prepared.values() for future in group]
        voice.stop()
        self.assertTrue(voice._speech_queue.empty())
        self.assertTrue(voice._render_queue.empty())
        self.assertTrue(all(future.cancelled() for future in futures))
        self.assertEqual(voice._prepared, {})
        voice.close()

    def test_wake_preroll_preserves_inline_request(self):
        stream = Mock()
        stream.read.return_value = b"new audio"
        replay = ReplayStream(stream, [b"Friday", b"open Spotify"])
        self.assertEqual(replay.read(512), b"Friday")
        self.assertEqual(replay.read(512), b"open Spotify")
        stream.read.assert_not_called()
        self.assertEqual(replay.read(512), b"new audio")

    def test_transient_microphone_error_recovers_without_disabling_wake(self):
        voice = VoiceService(Settings(), Mock())
        voice.available = True
        delivered = threading.Event()
        def received(text):
            delivered.set()
        with patch.object(voice, "_capture_and_transcribe", side_effect=[OSError(), "Friday open Spotify"]):
            voice.start(received, delivered.is_set)
            voice.set_wake_enabled(True)
            try:
                self.assertTrue(delivered.wait(2.5))
                self.assertTrue(voice._wake_enabled)
            finally:
                voice.close()

    def test_next_streamed_sentence_is_rendered_during_current_playback(self):
        voice = VoiceService(Settings(), Mock())
        voice.available = False
        second_ready = threading.Event()
        finished = threading.Event()
        played = []
        paths = []
        def render(text, path, generation):
            Path(path).write_bytes(text.encode())
            paths.append(path)
            if text.startswith("Second"):
                second_ready.set()
        def play(path, generation):
            self.assertTrue(second_ready.wait(1))
            played.append(Path(path).read_text())
            if len(played) == 2:
                finished.set()
        with patch.object(voice, "_render_cloud", side_effect=render), patch.object(voice, "_play_file", side_effect=play):
            voice.start(lambda text: None, lambda: False)
            voice.speak("First sentence.", prefetch=True)
            voice.speak("Second sentence.", prefetch=True)
            self.assertTrue(finished.wait(2))
            voice.close()
            for worker in voice._threads:
                worker.join(timeout=1)
        self.assertEqual(played, ["First sentence.", "Second sentence."])
        self.assertTrue(all(not Path(path).exists() for path in paths))

    @unittest.skipUnless(os.name == "nt", "Windows named events")
    def test_second_launch_signals_first_without_second_instance(self):
        name = "test-" + str(os.getpid())
        first = SingleInstance(name)
        second = SingleInstance(name)
        try:
            self.assertTrue(first.primary)
            self.assertFalse(second.primary)
            self.assertTrue(first.show_requested())
            self.assertFalse(first.show_requested())
        finally:
            second.close()
            first.close()


if __name__ == "__main__":
    unittest.main()
