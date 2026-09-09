"""Desktop smoke tests with a fake controller; no microphone or cloud access."""

import queue
import unittest
from unittest import mock

from assistant_core.settings import Settings
from assistant_core.ui import AssistantWindow


class FakeController:
    def __init__(self, persona):
        self.settings = Settings(
            persona=persona,
            voice="en-GB-RyanNeural" if persona == "alfred" else "en-IE-EmilyNeural",
            groq_voice="daniel" if persona == "alfred" else "diana",
        )
        self.events = queue.Queue()
        self.submitted = []
        self.closed = False
        self.stopped = False
        self.wake = False

    def submit(self, text):
        self.submitted.append(text)

    def listen_once(self):
        pass

    def set_wake_enabled(self, enabled):
        self.wake = enabled

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True

    def save_settings(self, values):
        self.settings = self.settings.updated(values)

    def diagnostics(self):
        self.events.put({"kind": "notice", "message": "Diagnostic result"})

    def clear_conversation(self):
        pass

    def clear_memories(self):
        pass

    def list_microphones(self):
        return [(2, "Test input")]

    def test_voice(self):
        pass


class WindowSmokeTests(unittest.TestCase):
    def test_personas_events_composer_settings_and_shutdown(self):
        for persona in ("friday", "alfred"):
            with self.subTest(persona=persona):
                controller = FakeController(persona)
                with mock.patch("assistant_core.ui.SystemTray.start", return_value=False):
                    window = AssistantWindow(controller)
                window.withdraw()
                try:
                    window.update_idletasks()
                    self.assertFalse(window._wake.get())
                    controller.events.put({"kind": "message", "role": "assistant", "text": "Hello from the worker."})
                    controller.events.put({"kind": "status", "state": "thinking", "detail": "Testing the event queue."})
                    controller.events.put({"kind": "notice", "message": "A readable notice."})
                    window._poll_events()
                    self.assertIn("Hello from the worker.", window.transcript.get("1.0", "end"))
                    self.assertIn("A readable notice.", window.transcript.get("1.0", "end"))
                    self.assertEqual(window.state_label.cget("text"), "THINKING")
                    self.assertEqual(window.talk_button.cget("state"), "disabled")
                    window.composer.insert("1.0", "  A question\nwith context  ")
                    window._send()
                    self.assertEqual(controller.submitted, ["A question\nwith context"])
                    self.assertEqual(window.composer.get("1.0", "end-1c"), "")
                    window._wake.set(True)
                    window._toggle_wake()
                    self.assertTrue(controller.wake)
                    window._speech.set(False)
                    window._toggle_speech()
                    self.assertFalse(controller.settings.speech_enabled)
                    window._stop()
                    self.assertTrue(controller.stopped)
                    window._open_settings()
                    dialog = window._dialog
                    dialog.withdraw()
                    self.assertEqual(dialog.api_key.cget("show"), "•")
                    self.assertEqual(dialog.model.get(), "auto")
                    self.assertFalse(dialog.start_with_windows.get())
                    self.assertEqual(dialog.voice_provider.get(), "edge")
                    self.assertEqual(dialog.groq_voice.get(), "daniel" if persona == "alfred" else "diana")
                    dialog.followup.delete(0, "end")
                    dialog.followup.insert(0, "1.5")
                    dialog._save()
                    self.assertTrue(dialog.winfo_exists())
                    self.assertIn("whole number", dialog.error_label.cget("text"))
                    dialog.followup.delete(0, "end")
                    dialog.followup.insert(0, "0")
                    dialog.start_with_windows.set(True)
                    dialog._save()
                    self.assertEqual(controller.settings.followup_seconds, 0)
                    self.assertTrue(controller.settings.start_with_windows)
                    self.assertFalse(dialog.winfo_exists())
                    window._clear_conversation()
                    self.assertNotIn("Hello from the worker.", window.transcript.get("1.0", "end"))
                    window._animate()
                    self.assertGreater(len(window.core_canvas.find_all()), 50)
                finally:
                    window._close()
                self.assertTrue(controller.closed)
                self.assertFalse(window._scheduled)

    def test_tray_commands_and_wake_overlay_stay_on_tk_thread(self):
        controller = FakeController("friday")
        controller.settings = controller.settings.updated({"wake_on_start": True})
        with mock.patch("assistant_core.ui.SystemTray.start", return_value=True):
            window = AssistantWindow(controller)
        window._tray.available = True
        try:
            window.update_idletasks()
            self.assertTrue(window._wake.get())

            window._hide_to_tray()
            self.assertTrue(window._hidden_to_tray)
            self.assertFalse(window._closed)
            self.assertFalse(controller.closed)

            window._tray.commands.put("show")
            window._poll_tray()
            self.assertFalse(window._hidden_to_tray)

            window._tray.commands.put("toggle_speech")
            window._poll_tray()
            self.assertFalse(controller.settings.speech_enabled)

            window._tray.commands.put("toggle_wake")
            window._poll_tray()
            self.assertFalse(controller.wake)

            controller.events.put({"kind": "wake_detected", "detail": "Wake word heard"})
            controller.events.put({"kind": "status", "state": "thinking", "detail": "Working"})
            window._poll_events()
            self.assertTrue(window._overlay.active)
            self.assertEqual(window._overlay._phase, "thinking")
            controller.events.put({"kind": "status", "state": "speaking", "detail": "Speaking"})
            window._poll_events()
            self.assertEqual(window._overlay._phase, "speaking")
            controller.events.put({"kind": "status", "state": "ready", "detail": "Ready"})
            window._poll_events()
            self.assertIsNotNone(window._overlay._fade_started)

            window._tray.commands.put("exit")
            window._poll_tray()
            self.assertTrue(window._closed)
            self.assertTrue(controller.closed)
        finally:
            window._close()

    def test_background_launch_remains_hidden_and_can_be_restored(self):
        def start_tray(tray):
            tray.available = True
            return True
        with mock.patch("assistant_core.ui.SystemTray.start", autospec=True, side_effect=start_tray):
            window = AssistantWindow(FakeController("friday"), background=True)
        try:
            window.after(450, window.quit)
            window.mainloop()
            self.assertEqual(window.state(), "withdrawn")
            self.assertTrue(window._hidden_to_tray)
            self.assertFalse(window._closed)
            window._show_window()
            window.update_idletasks()
            self.assertEqual(window.state(), "normal")
        finally:
            window._close()


if __name__ == "__main__":
    unittest.main()
