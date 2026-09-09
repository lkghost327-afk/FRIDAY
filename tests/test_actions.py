"""Action tests use fake devices/network responses and never launch PC apps."""

import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

from assistant_core.actions import ActionRouter, AppWindow, InstalledApp, WM_CLOSE


class ActionRouterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.events = []
        self.alert = threading.Event()

        def emit(kind, **payload):
            self.events.append((kind, payload))
            self.alert.set()

        self.emit = emit
        self.router = ActionRouter(self.base, "FRIDAY", self.emit)

    def tearDown(self):
        self.router.close()
        self.temp.cleanup()

    def restart(self):
        self.router.close()
        self.router = ActionRouter(self.base, "FRIDAY", self.emit)

    def test_conversation_falls_through(self):
        self.assertIsNone(self.router.handle("How would an arc reactor work?"))
        self.assertIsNone(self.router.handle("Why do I feel like time is moving slowly?"))

    def test_time_and_persona_prefix(self):
        result = self.router.handle("Hey Friday, what time is it?")
        self.assertIn("It is", result)
        self.assertIn(dt.datetime.now().strftime("%Y"), result)
        self.assertIn("UTC", result)

    def test_closed_tool_schema_and_types(self):
        for tool in self.router.tools:
            self.assertFalse(tool["function"]["parameters"]["additionalProperties"])
        with patch.object(self.router, "_open_app") as opener:
            for arguments in ({"app": "notepad", "command": "evil"}, {"app": ["notepad"]}, {},
                              {"app": "x" * 121}):
                self.assertIn("couldn't", self.router.execute("open_app", arguments))
            opener.assert_not_called()
        tools = {tool["function"]["name"]: tool["function"] for tool in self.router.tools}
        self.assertIn("close_app", tools)
        self.assertIn("list_installed_apps", tools)
        self.assertNotIn("enum", tools["open_app"]["parameters"]["properties"]["app"])
        self.assertEqual(tools["open_app"]["parameters"]["properties"]["app"]["maxLength"], 120)
        self.assertIn("not supported", self.router.execute("run_shell", {"command": "whoami"}))
        self.assertIn("object", self.router.execute("get_time", []))

    def test_nonfinite_bool_and_out_of_range_numbers_rejected(self):
        with patch.object(self.router, "_set_volume") as setter:
            for value in (float("nan"), float("inf"), True, -1, 101, "40"):
                self.assertIn("couldn't", self.router.execute("set_volume", {"action": "set", "percent": value}))
            setter.assert_not_called()

    def test_tools_return_copy(self):
        definitions = self.router.tools
        definitions[0]["function"]["name"] = "run_shell"
        self.assertEqual(self.router.tools[0]["function"]["name"], "get_time")

    def test_safe_application_launch_arguments(self):
        executable = r"C:\Windows\System32\notepad.exe"
        with patch("assistant_core.actions.platform.system", return_value="Windows"), \
                patch.object(self.router, "_find_executable", return_value=executable), \
                patch("assistant_core.actions.subprocess.Popen") as launch:
            result = self.router.handle("open notepad")
            self.assertIn("open request", result)
            launch.assert_called_once_with([executable], shell=False, close_fds=True)

    def test_missing_app_does_not_claim_opened(self):
        with patch("assistant_core.actions.platform.system", return_value="Windows"), \
                patch.object(self.router, "_find_executable", return_value=None), \
                patch.object(self.router, "_installed_apps", return_value=()), \
                patch("assistant_core.actions.subprocess.Popen") as launch:
            self.assertIn("couldn't find", self.router.handle("open chrome"))
            launch.assert_not_called()

    def test_spotify_prefers_discovered_desktop_app_over_website(self):
        executable = self.base / "Spotify.exe"
        executable.write_bytes(b"test fixture")
        installed = (InstalledApp("Spotify", "executable", str(executable), ("spotify",), "start"),)
        with patch("assistant_core.actions.platform.system", return_value="Windows"), \
                patch.object(self.router, "_find_executable", return_value=str(executable)), \
                patch.object(self.router, "_installed_apps", return_value=installed), \
                patch("assistant_core.actions.subprocess.Popen") as launch, \
                patch("assistant_core.actions.webbrowser.open") as browser:
            result = self.router.handle("open Spotify")
        self.assertEqual(result, "Sent Spotify an open request.")
        launch.assert_called_once_with([str(executable)], shell=False, close_fds=True)
        browser.assert_not_called()

    def test_explicit_spotify_website_still_uses_browser(self):
        installed = (InstalledApp("Spotify", "shell_app", "Spotify.App!Spotify", ("spotify",), "start"),)
        with patch("assistant_core.actions.platform.system", return_value="Windows"), \
                patch.object(self.router, "_installed_apps", return_value=installed), \
                patch("assistant_core.actions.os.startfile") as startfile, \
                patch("assistant_core.actions.webbrowser.open", return_value=True) as browser:
            result = self.router.handle("open Spotify website")
        self.assertIn("spotify", result.lower())
        browser.assert_called_once_with("https://open.spotify.com/", new=2)
        startfile.assert_not_called()

    def test_start_app_identifier_uses_windows_shell_namespace(self):
        installed = (InstalledApp("Discord", "shell_app", "com.squirrel.Discord.Discord", ("discord",), "start"),)
        with patch("assistant_core.actions.platform.system", return_value="Windows"), \
                patch.object(self.router, "_installed_apps", return_value=installed), \
                patch("assistant_core.actions.os.startfile") as startfile, \
                patch("assistant_core.actions.subprocess.Popen") as launch:
            result = self.router.handle("launch discord")
        self.assertEqual(result, "Sent Discord an open request.")
        startfile.assert_called_once_with(r"shell:AppsFolder\com.squirrel.Discord.Discord")
        launch.assert_not_called()

    def test_unknown_or_command_like_app_names_never_become_launch_targets(self):
        with patch("assistant_core.actions.platform.system", return_value="Windows"), \
                patch.object(self.router, "_installed_apps", return_value=()), \
                patch("assistant_core.actions.subprocess.Popen") as launch, \
                patch("assistant_core.actions.os.startfile") as startfile, \
                patch("assistant_core.actions.webbrowser.open") as browser:
            for command in ("open notepad; calc", "open C:\\Windows\\System32\\cmd.exe", "open https://evil.invalid"):
                self.assertIn("couldn't find", self.router.handle(command))
        launch.assert_not_called()
        startfile.assert_not_called()
        browser.assert_not_called()

    def test_installed_app_discovery_is_lazily_cached_even_when_empty(self):
        spotify = InstalledApp("Spotify", "shell_app", "Spotify.App!Spotify", ("spotify",), "start")
        with patch.object(self.router, "_discover_installed_apps", return_value=[spotify]) as discover:
            self.assertEqual(self.router._installed_apps(), (spotify,))
            self.assertEqual(self.router._installed_apps(), (spotify,))
            discover.assert_called_once()
            self.router._installed_apps(refresh=True)
            self.assertEqual(discover.call_count, 2)
        self.router._app_cache = ()
        self.router._app_cache_time = 0
        with patch.object(self.router, "_discover_installed_apps", return_value=[]) as discover:
            self.assertEqual(self.router._installed_apps(), ())
            self.assertEqual(self.router._installed_apps(), ())
            discover.assert_called_once()

    def test_list_installed_apps_is_read_only_and_uses_display_names(self):
        installed = (
            InstalledApp("Spotify", "shell_app", "Spotify.App!Spotify", ("spotify",), "start"),
            InstalledApp("Discord", "shell_app", "Discord.App!Discord", ("discord",), "start"),
        )
        with patch("assistant_core.actions.platform.system", return_value="Windows"), \
                patch.object(self.router, "_installed_apps", return_value=installed), \
                patch("assistant_core.actions.subprocess.Popen") as launch, \
                patch("assistant_core.actions.os.startfile") as startfile:
            result = self.router.handle("list installed apps")
        self.assertIn("Discord, Spotify", result)
        launch.assert_not_called()
        startfile.assert_not_called()

    def test_browser_allowlist_and_encoding(self):
        with patch("assistant_core.actions.webbrowser.open", return_value=True) as browser:
            self.assertIn("youtube", self.router.handle("open YouTube"))
            browser.assert_called_with("https://www.youtube.com/", new=2)
            result = self.router.execute("open_search", {"query": "science & art + code"})
            self.assertIn("q=science+%26+art+%2B+code", result)
            self.assertIn("not read", result)
            self.assertIn("couldn't", self.router.execute("open_website", {"site": "file:///C:/"}))
            self.assertEqual(browser.call_count, 2)

    def test_browser_failure_is_reported(self):
        with patch("assistant_core.actions.webbrowser.open", return_value=False):
            self.assertIn("did not accept", self.router.handle("open github"))

    def test_harmful_cleanup_never_launches_process(self):
        with patch("assistant_core.actions.subprocess.Popen") as launch:
            self.assertIn("lose work", self.router.handle("clear ram"))
            self.assertIsNone(self.router.handle("run powershell Remove-Item C:\\"))
            launch.assert_not_called()

    def test_close_app_posts_only_normal_wm_close_to_one_matching_window(self):
        installed = (InstalledApp("Spotify", "executable", r"C:\Apps\Spotify.exe", ("spotify",), "start"),)
        window = AppWindow(410, 9001, "Spotify Premium", "Spotify.exe")
        with patch("assistant_core.actions.platform.system", return_value="Windows"), \
                patch.object(self.router, "_installed_apps", return_value=installed), \
                patch.object(self.router, "_user_windows", return_value=[window]), \
                patch.object(self.router, "_post_window_close", return_value=True) as close:
            result = self.router.handle("close Spotify")
        self.assertIn("close normally", result)
        self.assertIn("nothing was force-closed", result)
        close.assert_called_once_with(410)

    def test_quit_parser_preserves_app_name(self):
        with patch.object(self.router, "_close_app", return_value="asked") as close:
            self.assertEqual(self.router.handle("Could you please quit Discord app?"), "asked")
        close.assert_called_once_with(app="Discord")

    def test_close_app_refuses_protected_assistant_shell_terminal_and_security_apps(self):
        with patch("assistant_core.actions.platform.system", return_value="Windows"), \
                patch.object(self.router, "_user_windows") as windows, \
                patch.object(self.router, "_post_window_close") as close:
            for name in ("FRIDAY", "Alfred", "File Explorer", "PowerShell", "Windows Terminal",
                         "Task Manager", "Windows Security", "Windows Settings"):
                self.assertIn("protected", self.router.execute("close_app", {"app": name}))
        windows.assert_not_called()
        close.assert_not_called()

    def test_close_app_does_not_close_browser_host_or_ambiguous_windows(self):
        installed = (InstalledApp("Spotify", "shell_app", "Spotify.App!Spotify", ("spotify",), "start"),)
        chrome = AppWindow(1, 10, "Spotify", "chrome.exe")
        with patch("assistant_core.actions.platform.system", return_value="Windows"), \
                patch.object(self.router, "_installed_apps", return_value=installed), \
                patch.object(self.router, "_user_windows", return_value=[chrome]), \
                patch.object(self.router, "_post_window_close") as close:
            self.assertIn("does not appear", self.router.handle("close Spotify"))
            close.assert_not_called()
        windows = [AppWindow(2, 20, "Spotify", "Spotify.exe"),
                   AppWindow(3, 21, "Spotify Mini", "Spotify.exe")]
        with patch("assistant_core.actions.platform.system", return_value="Windows"), \
                patch.object(self.router, "_installed_apps", return_value=installed), \
                patch.object(self.router, "_user_windows", return_value=windows), \
                patch.object(self.router, "_post_window_close") as close:
            self.assertIn("ambiguous", self.router.handle("close Spotify"))
            close.assert_not_called()

    def test_close_app_reports_not_running_and_failed_close_accurately(self):
        installed = (InstalledApp("Discord", "shell_app", "Discord.App!Discord", ("discord",), "start"),)
        with patch("assistant_core.actions.platform.system", return_value="Windows"), \
                patch.object(self.router, "_installed_apps", return_value=installed), \
                patch.object(self.router, "_user_windows", return_value=[]), \
                patch.object(self.router, "_post_window_close") as close:
            self.assertIn("does not appear", self.router.handle("quit Discord"))
            close.assert_not_called()
        with patch("assistant_core.actions.platform.system", return_value="Windows"), \
                patch.object(self.router, "_installed_apps", return_value=installed), \
                patch.object(self.router, "_user_windows", return_value=[AppWindow(9, 99, "Discord", "Discord.exe")]), \
                patch.object(self.router, "_post_window_close", return_value=False):
            result = self.router.execute("close_app", {"app": "Discord"})
        self.assertIn("did not accept", result)
        self.assertIn("nothing was force-closed", result)

    def test_wm_close_uses_postmessage_without_process_termination(self):
        post = Mock(return_value=1)
        fake_ctypes = types.SimpleNamespace(windll=types.SimpleNamespace(user32=types.SimpleNamespace(PostMessageW=post)))
        with patch("assistant_core.actions.platform.system", return_value="Windows"), \
                patch("assistant_core.actions.ctypes", fake_ctypes):
            self.assertTrue(ActionRouter._post_window_close(55))
        post.assert_called_once_with(55, WM_CLOSE, 0, 0)

    def test_notes_roundtrip_preserve_case_and_unicode(self):
        result = self.router.handle("take a note: Buy Café beans at 5 PM.")
        self.assertIn("Buy Café beans at 5 PM.", result)
        self.restart()
        self.assertIn("Buy Café beans at 5 PM.", self.router.handle("show notes"))
        data = json.loads((self.base / "data/notes.json").read_text(encoding="utf-8"))
        self.assertEqual(len(data), 1)
        self.assertEqual(list((self.base / "data").glob("*.tmp")), [])

    def test_failed_note_write_does_not_claim_or_keep_saved_note(self):
        with patch("assistant_core.actions.os.replace", side_effect=PermissionError):
            self.assertIn("couldn't", self.router.handle("take a note test"))
        self.assertIn("no saved notes", self.router.handle("show notes"))

    def test_corrupt_data_is_preserved(self):
        self.router.close()
        path = self.base / "data/notes.json"
        path.write_text("{broken", encoding="utf-8")
        self.restart()
        self.assertIn("preserved", self.router.handle("take a note new text"))
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_reminder_duration_parsing_and_cancellation(self):
        self.assertIn("saved", self.router.handle("remind me in 1 hour and 30 minutes to stretch"))
        pending = self.router._reminders[0]
        self.assertAlmostEqual(pending["due"] - pending["created"], 5400, places=2)
        self.assertEqual(pending["text"], "stretch")
        self.assertIn(pending["id"], self.router.handle("list reminders"))
        self.assertIn("Cancelled", self.router.handle("cancel reminder " + pending["id"]))
        self.restart()
        self.assertIn("no pending", self.router.handle("list reminders"))

    def test_spoken_timer_and_alternate_reminder_syntax(self):
        self.assertIn("saved", self.router.handle("set a timer for five minutes"))
        self.assertIn("saved", self.router.handle("remind me to call mum in ten minutes"))
        self.assertEqual([item["due"] - item["created"] for item in self.router._reminders], [300, 600])

    def test_flexible_spoken_duration(self):
        self.assertIn("saved", self.router.handle("Could you please set a 5-minute timer?"))
        self.assertIn("saved", self.router.handle("remind me in half an hour to stretch"))
        self.assertIn("saved", self.router.handle("set a timer for a quarter of an hour"))
        self.assertEqual([item["due"] - item["created"] for item in self.router._reminders], [300, 1800, 900])

    def test_absolute_reminder_time(self):
        result = self.router.handle("remind me tomorrow at 5:30 pm to check mail")
        self.assertIn("saved", result)
        due = dt.datetime.fromtimestamp(self.router._reminders[0]["due"])
        self.assertEqual((due.hour, due.minute), (17, 30))
        self.assertEqual(due.date(), dt.datetime.now().date() + dt.timedelta(days=1))
        self.assertIn("valid time", self.router.handle("remind me at 25:90 to check mail"))

    def test_invalid_reminders_do_not_persist(self):
        invalid = [
            {"text": "test", "seconds": 0}, {"text": "test", "seconds": -1},
            {"text": "test", "seconds": True}, {"text": "test", "seconds": float("nan")},
            {"text": "test"}, {"text": "test", "seconds": 10, "at": "2099-01-01T10:00:00"},
            {"text": "test", "at": "2000-01-01T10:00:00"},
            {"text": "test", "at": (dt.datetime.now() + dt.timedelta(days=1)).strftime("%Y-%m-%d")},
        ]
        for args in invalid:
            self.assertIn("couldn't", self.router.execute("set_reminder", args))
        self.assertEqual(self.router._reminders, [])

    def test_overdue_reminder_delivered_after_restart_once(self):
        self.router.execute("set_reminder", {"text": "stretch now", "seconds": 60})
        self.router.close()
        path = self.base / "data/reminders.json"
        records = json.loads(path.read_text(encoding="utf-8"))
        records[0]["due"] = time.time() - 1
        path.write_text(json.dumps(records), encoding="utf-8")
        self.restart()
        self.assertTrue(self.alert.wait(2), "Overdue reminder should fire at startup")
        self.assertEqual(self.events[0], ("reminder", {"text": "stretch now", "id": records[0]["id"]}))
        self.restart()
        self.assertEqual(len(self.events), 1)
        self.assertEqual(json.loads(path.read_text())[0]["status"], "delivered")

    def test_close_stops_scheduler(self):
        self.router.close()
        self.assertFalse(self.router._scheduler.is_alive())
        self.assertIn("closing", self.router.execute("add_note", {"text": "late"}))
        with patch.object(self.router, "_take_screenshot") as screenshot:
            self.assertIn("closing", self.router.handle("take a screenshot"))
            screenshot.assert_not_called()

    def test_arithmetic_rejects_code_and_huge_exponents(self):
        self.assertEqual(self.router.handle("calculate (18 + 7) * 4"), "(18 + 7) * 4 = 100")
        for expression in ("__import__('os').system('bad')", "2 ** 1000000", "1 / 0", "True + 1", "[1] * 100", "(-1) ** 0.5"):
            result = self.router.execute("calculate", {"expression": expression})
            self.assertIn("couldn't", result)

    def test_screenshot_only_explicit_and_local(self):
        self.assertNotIn("take_screenshot", [tool["function"]["name"] for tool in self.router.tools])
        with patch.object(self.router, "_take_screenshot", return_value="Saved locally") as screenshot:
            self.assertIsNone(self.router.handle("What would be in a screenshot?"))
            screenshot.assert_not_called()
            self.assertEqual(self.router.handle("take a screenshot"), "Saved locally")
            screenshot.assert_called_once()

    def test_system_status_reports_total_and_available_memory(self):
        fake = Mock()
        fake.virtual_memory.return_value = types.SimpleNamespace(total=16 * 1024**3, available=6 * 1024**3, percent=62.5)
        fake.cpu_count.side_effect = lambda logical: 12 if logical else 6
        fake.cpu_percent.return_value = 23
        fake.sensors_battery.return_value = types.SimpleNamespace(percent=82, power_plugged=True)
        with patch("assistant_core.actions.importlib.import_module", return_value=fake), \
                patch("assistant_core.actions.shutil.disk_usage", return_value=types.SimpleNamespace(total=512 * 1024**3, free=100 * 1024**3)):
            result = self.router.handle("system status")
        self.assertIn("16.0 GiB total, 6.0 GiB available", result)
        self.assertIn("6 physical cores, 12 logical processors", result)
        self.assertIn("82% (plugged in)", result)

    def test_live_search_returns_sources_and_skips_nonweb_links(self):
        ddgs = Mock()
        ddgs.DDGS.return_value.text.return_value = [
            {"title": "Science news", "body": "A real result.", "href": "https://example.org/news"},
            {"title": "bad", "href": "file:///C:/secrets.txt"},
        ]
        with patch("assistant_core.actions.importlib.import_module", return_value=ddgs):
            result = self.router.handle("search the web for science")
        self.assertIn("A real result.", result)
        self.assertIn("https://example.org/news", result)
        self.assertNotIn("file:///", result)
        ddgs.DDGS.assert_called_once_with(timeout=10)

    def test_weather_requires_city_and_reports_source(self):
        self.assertIn("Tell me a city", self.router.handle("what's the weather"))
        requests = Mock()
        geo = Mock()
        geo.json.return_value = {"results": [{"name": "Mumbai", "admin1": "Maharashtra", "country": "India", "latitude": 19, "longitude": 72}]}
        weather = Mock()
        weather.json.return_value = {"current": {"temperature_2m": 27, "apparent_temperature": 31, "weather_code": 2, "time": "2026-09-06T10:00"}, "timezone": "Asia/Kolkata"}
        requests.get.side_effect = [geo, weather]
        with patch("assistant_core.actions.importlib.import_module", return_value=requests):
            result = self.router.handle("weather in Mumbai")
        self.assertIn("Mumbai, Maharashtra, India", result)
        self.assertIn("27 °C", result)
        self.assertIn("Open-Meteo", result)
        self.assertEqual(requests.get.call_args_list[0].kwargs["params"]["name"], "Mumbai")
        self.assertEqual(requests.get.call_args_list[1].kwargs["timeout"], (4, 10))

    def test_brightness_reports_actual_value(self):
        sbc = Mock()
        sbc.get_brightness.side_effect = [[40], [61]]
        with patch("assistant_core.actions.importlib.import_module", return_value=sbc):
            result = self.router.handle("brightness 60%")
        sbc.set_brightness.assert_called_once_with(60)
        self.assertEqual(result, "Display brightness: 61%.")

    def test_volume_reports_verified_level_and_keeps_mute_state(self):
        comtypes = Mock()
        audio = Mock()
        endpoint = audio.AudioUtilities.GetSpeakers.return_value.EndpointVolume
        endpoint.GetMasterVolumeLevelScalar.side_effect = [0.20, 0.41]
        endpoint.GetMute.return_value = 1
        with patch("assistant_core.actions.platform.system", return_value="Windows"), \
                patch("assistant_core.actions.importlib.import_module", side_effect=[comtypes, audio]):
            result = self.router.handle("volume 40%")
        endpoint.SetMasterVolumeLevelScalar.assert_called_once_with(0.4, None)
        self.assertIn("41%", result)
        self.assertIn("still muted", result)
        comtypes.CoUninitialize.assert_called_once()


if __name__ == "__main__":
    unittest.main()
