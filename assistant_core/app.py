"""Import-safe entry point for both source launches and PyInstaller builds."""

import argparse
import json
from pathlib import Path
import sys

from .settings import Settings


def data_directory(entry_path, persona):
    """Keep credentials and personal state outside the source repository."""
    import os
    name = "ALFRED" if persona == "alfred" else "FRIDAY"
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    return local / "FanAssistants" / name


def main(persona, entry_path):
    parser = argparse.ArgumentParser(description=f"{persona.title()} desktop assistant")
    parser.add_argument("--check", action="store_true", help="Check dependencies and AI connection without opening the UI")
    parser.add_argument("--smoke-ui", action="store_true", help="Open then close the UI without microphone or speech")
    parser.add_argument("--background", action="store_true", help="Start in the system tray")
    args = parser.parse_args()
    base_dir = data_directory(entry_path, persona)
    if args.check:
        from .diagnostics import run_checks
        result = run_checks(base_dir, persona, live=True)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1
    from .controller import AssistantController
    from .ui import AssistantWindow
    from .lifecycle import SingleInstance
    from .startup import WindowsStartup
    instance = None if args.smoke_ui else SingleInstance(persona, show_existing=not args.background)
    if instance is not None and not instance.primary:
        instance.close()
        return 0
    startup = None if args.smoke_ui else WindowsStartup(persona, entry_path)
    controller = AssistantController(base_dir, persona, startup=startup)
    window = AssistantWindow(controller, background=args.background)
    if args.smoke_ui:
        window.after(2000, window._exit)
    else:
        controller.start()
        def poll_launch():
            if window._closed:
                return
            if instance.show_requested():
                window._show_window()
            window._schedule(250, poll_launch)
        window._schedule(250, poll_launch)
    try:
        window.mainloop()
    finally:
        controller.close()
        if instance is not None:
            instance.close()
    return 0


def launch(persona, entry_path):
    try:
        return main(persona, entry_path)
    except Exception as error:
        message = (f"{persona.title()} could not start ({type(error).__name__}).\n\n"
                   "Run Setup.bat in this project folder, then try again.\n"
                   "Run Check.bat for connection and dependency diagnostics.")
        if sys.stderr is not None:
            print(message, file=sys.stderr)
        if sys.platform == "win32" and not any(a in sys.argv for a in ("--check", "--smoke-ui")):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "Assistant startup", 0x10)
        return 1
