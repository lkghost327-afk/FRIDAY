"""Per-user Windows sign-in startup; independent entries for the two assistants."""

from pathlib import Path
import subprocess
import sys

try:
    import winreg
except ImportError:
    winreg = None


def launch_command(entry_path):
    """Register the real EXE, never PyInstaller's temporary extraction directory."""
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        arguments = [str(executable)]
    else:
        pythonw = executable.with_name("pythonw.exe")
        if not pythonw.is_file():
            raise OSError("Windows startup needs pythonw.exe. Run Setup.bat or use the built EXE.")
        entry = Path(entry_path).resolve()
        if not entry.is_file():
            raise OSError("The assistant's launcher is missing. Launch it from its project folder again.")
        arguments = [str(pythonw), str(entry)]
    command = subprocess.list2cmdline([*arguments, "--background"])
    # Microsoft documents a 260-character limit for Run commands.
    if len(command) > 260:
        raise ValueError("The startup path is too long. Move the EXE to a shorter folder path and try again.")
    return command


class WindowsStartup:
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def __init__(self, persona, entry_path):
        if persona not in {"friday", "alfred"}:
            raise ValueError("Unknown assistant persona.")
        self.value_name = "FanAssistants." + persona.upper()
        self.entry_path = entry_path

    @staticmethod
    def _require_windows():
        if winreg is None:
            raise OSError("Start with Windows is only available on Windows.")

    def get_command(self):
        self._require_windows()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_QUERY_VALUE) as key:
                return winreg.QueryValueEx(key, self.value_name)[0]
        except FileNotFoundError:
            return None

    def restore(self, command):
        """Restore only this persona's value, including when a settings save fails."""
        self._require_windows()
        if command is None:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, self.value_name)
            except FileNotFoundError:
                pass
        else:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, self.value_name, 0, winreg.REG_SZ, command)

    def set_enabled(self, enabled):
        command = launch_command(self.entry_path) if enabled else None
        if self.get_command() != command:
            self.restore(command)

    def refresh(self):
        """Follow a moved launcher only if startup is already registered.

        An externally removed entry stays off. Windows Startup Apps can further
        disable this Run entry; we never modify its separate approval setting.
        """
        enabled = self.get_command() is not None
        if enabled:
            self.set_enabled(True)
        return enabled
