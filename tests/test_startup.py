"""Startup regression checks; never add entries to the actual Windows Run key."""

from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import uuid

from assistant_core import startup
from assistant_core.lifecycle import SingleInstance
from assistant_core.settings import Settings


class StartupCommandTests(unittest.TestCase):
    def test_packaged_launcher_uses_real_exe_and_quotes_spaces(self):
        path = str(Path("C:/Program Files/Fan Assistants/FRIDAY.exe").resolve())
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", path):
            command = startup.launch_command("C:/Temp/_MEI999/friday_app.py")
        self.assertEqual(command, subprocess.list2cmdline([path, "--background"]))
        self.assertNotIn("_MEI", command)

    def test_source_launcher_uses_pythonw_and_absolute_script(self):
        with TemporaryDirectory(prefix="assistant startup ") as tmp:
            python = Path(tmp) / "python.exe"
            pythonw = Path(tmp) / "pythonw.exe"
            entry = Path(tmp) / "friday_app.py"
            pythonw.touch()
            entry.touch()
            with patch.object(sys, "frozen", False, create=True), patch.object(sys, "executable", str(python)):
                self.assertEqual(startup.launch_command(entry),
                                 subprocess.list2cmdline([str(pythonw), str(entry), "--background"]))
                pythonw.unlink()
                with self.assertRaisesRegex(OSError, "pythonw"):
                    startup.launch_command(entry)

    def test_rejects_command_longer_than_windows_limit(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", "C:/" + "x" * 250 + "/FRIDAY.exe"):
            with self.assertRaisesRegex(ValueError, "shorter"):
                startup.launch_command("unused")

    def test_setting_defaults_off_validates_and_round_trips(self):
        self.assertFalse(Settings().start_with_windows)
        with self.assertRaises(ValueError):
            Settings().updated({"start_with_windows": "yes"})
        with TemporaryDirectory() as tmp:
            Settings().updated({"start_with_windows": True}).save(tmp)
            self.assertTrue(Settings.load(tmp, "friday").start_with_windows)

    @unittest.skipUnless(os.name == "nt", "Windows named events")
    def test_background_duplicate_does_not_show_existing_window(self):
        name = "startup-test-" + uuid.uuid4().hex
        first = SingleInstance(name)
        second = SingleInstance(name, show_existing=False)
        try:
            self.assertTrue(first.primary)
            self.assertFalse(second.primary)
            self.assertFalse(first.show_requested())
        finally:
            second.close()
            first.close()


@unittest.skipUnless(startup.winreg is not None, "Windows registry")
class StartupRegistryTests(unittest.TestCase):
    def setUp(self):
        # An isolated test key exercises real Windows APIs without enabling startup.
        self.registry_path = r"Software\FanAssistants\StartupTest-" + uuid.uuid4().hex
        self.key_patch = patch.object(startup.WindowsStartup, "RUN_KEY", self.registry_path)
        self.key_patch.start()
        self.command_patch = patch.object(startup, "launch_command", return_value='"C:\\Fan Assistants\\FRIDAY.exe" --background')
        self.command_patch.start()
        self.friday = startup.WindowsStartup("friday", "unused")
        self.alfred = startup.WindowsStartup("alfred", "unused")

    def tearDown(self):
        try:
            startup.winreg.DeleteKey(startup.winreg.HKEY_CURRENT_USER, self.registry_path)
        except FileNotFoundError:
            pass
        self.command_patch.stop()
        self.key_patch.stop()

    def test_enable_disable_is_independent_and_idempotent(self):
        self.assertIsNone(self.friday.get_command())
        self.friday.set_enabled(True)
        self.alfred.set_enabled(True)
        expected = self.friday.get_command()
        self.assertIn("--background", expected)
        self.friday.set_enabled(False)
        self.friday.set_enabled(False)
        self.assertIsNone(self.friday.get_command())
        self.assertEqual(self.alfred.get_command(), expected)

    def test_refresh_follows_moved_exe_but_preserves_removed_entry(self):
        self.friday.restore('"C:\\Old Folder\\FRIDAY.exe" --background')
        self.assertTrue(self.friday.refresh())
        self.assertIn("Fan Assistants", self.friday.get_command())
        self.friday.set_enabled(False)
        self.assertFalse(self.friday.refresh())
        self.assertIsNone(self.friday.get_command())

    def test_failed_registration_does_not_claim_success(self):
        with patch.object(startup.winreg, "CreateKeyEx", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.friday.set_enabled(True)
        self.assertIsNone(self.friday.get_command())


if __name__ == "__main__":
    unittest.main()
