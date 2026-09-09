"""Read-only diagnostics: never opens a microphone or plays audio."""

import importlib.util
from .brain import Brain, BrainError
from .settings import Settings


def run_checks(base_dir, persona, live=False):
    settings = Settings.load(base_dir, persona)
    modules = {name: importlib.util.find_spec(name) is not None for name in
               ("customtkinter", "groq", "speech_recognition", "pyaudio", "edge_tts", "pygame", "psutil", "pycaw", "ddgs",
                "PIL.ImageGrab", "screen_brightness_control", "win32com.client", "pythoncom", "pystray", "vosk")}
    from .wake import model_directory
    result = {"persona": persona, "dependencies": modules, "key_configured": bool(settings.api_key),
              "configured_model": settings.model, "ok": all(modules.values())}
    result["local_wake_model"] = (model_directory() / "am/final.mdl").is_file()
    if live:
        try:
            result["connection"] = Brain(settings).check_connection()
        except BrainError as error:
            result["connection"] = str(error)
            result["ok"] = False
    return result
