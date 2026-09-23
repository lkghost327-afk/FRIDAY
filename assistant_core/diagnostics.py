"""Read-only diagnostics: never opens a microphone or plays audio."""

import importlib.util
from .brain import Brain, BrainError
from .settings import Settings


def run_checks(base_dir, persona, live=False):
    settings = Settings.load(base_dir, persona)
    modules = {name: importlib.util.find_spec(name) is not None for name in
               ("customtkinter", "groq", "speech_recognition", "pyaudio", "edge_tts", "pygame", "psutil", "pycaw", "ddgs",
                "PIL.ImageGrab", "screen_brightness_control", "win32com.client", "pythoncom", "pystray", "vosk",
                "miniaudio", "aec_audio_processing", "pywinauto")}
    from .wake import model_directory
    result = {"persona": persona, "dependencies": modules, "key_configured": bool(settings.api_key),
              "configured_model": settings.model, "ok": all(modules.values())}
    result["local_wake_model"] = (model_directory() / "am/final.mdl").is_file()
    from .ownership import details
    result['ownership'] = details(persona)
    # Importing metadata alone misses missing native DLLs in frozen releases.
    try:
        import io
        import wave
        import miniaudio
        from pywinauto import Desktop
        from .audio_io import AcousticProcessor
        processor = AcousticProcessor()
        processor.playback(bytes(960))
        assert len(processor.capture(bytes(320))) == 320
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(bytes(3200))
        decoded = miniaudio.decode(buffer.getvalue(), nchannels=1, sample_rate=16000)
        assert len(decoded.samples) > 0
        if result['local_wake_model']:
            from .wake import LocalWake
            LocalWake(persona).feed(bytes(640))
        result['native_audio_and_automation'] = 'passed'
    except Exception as error:
        result['native_audio_and_automation'] = type(error).__name__
        result['ok'] = False
    if live:
        try:
            result["connection"] = Brain(settings).check_connection()
        except BrainError as error:
            result["connection"] = str(error)
            result["ok"] = False
    return result
