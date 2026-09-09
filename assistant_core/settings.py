"""Persona-specific configuration. Secrets never enter settings JSON or logs."""

from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
import re
import tempfile


def atomic_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.stem + "-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@dataclass(frozen=True)
class Settings:
    persona: str = "friday"
    model: str = "auto"
    api_key: str = ""
    voice: str = "en-US-EmmaMultilingualNeural"
    voice_provider: str = "edge"
    groq_voice: str = "diana"
    speech_enabled: bool = True
    microphone_index: int | None = None
    recognition_language: str = "en-IN"
    stt_provider: str = "auto"
    followup_seconds: int = 15
    wake_on_start: bool = False
    start_with_windows: bool = False

    @property
    def display_name(self):
        return "ALFRED" if self.persona == "alfred" else "F.R.I.D.A.Y"

    @property
    def accent(self):
        return "#E7BD63" if self.persona == "alfred" else "#46DFFF"

    @classmethod
    def load(cls, base_dir, persona):
        from dotenv import dotenv_values
        base_dir = Path(base_dir)
        defaults = cls(persona=persona,
                       voice="en-GB-RyanNeural" if persona == "alfred" else "en-US-EmmaMultilingualNeural",
                       groq_voice="daniel" if persona == "alfred" else "diana")
        path = base_dir / "settings.json"
        values = {}
        if path.exists():
            try:
                values = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(values, dict):
                    values = {}
            except (OSError, ValueError):
                pass
        editable = set(asdict(defaults)) - {"persona", "api_key"}
        valid = {k: v for k, v in values.items() if k in editable}
        try:
            settings = defaults.updated(valid)
        except ValueError:
            settings = defaults
        env = dotenv_values(base_dir / ".env")
        key = env.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY", "")
        return replace(settings, api_key=key.strip())

    def updated(self, values):
        editable = set(asdict(self)) - {"persona"}
        if set(values) - editable:
            raise ValueError("Unknown setting: " + ", ".join(sorted(set(values) - editable)))
        result = replace(self, **values)
        for field in ("model", "api_key", "voice", "voice_provider", "groq_voice",
                      "recognition_language", "stt_provider"):
            value = getattr(result, field)
            if not isinstance(value, str) or "\n" in value or "\r" in value:
                raise ValueError(f"Invalid {field.replace('_', ' ')}.")
        result = replace(result, model=result.model.strip() or "auto", api_key=result.api_key.strip(), voice=result.voice.strip())
        if len(result.api_key) > 512 or len(result.model) > 128:
            raise ValueError("API key or model value is too long.")
        if not re.fullmatch(r"[a-z]{2,3}-[A-Z]{2}-[A-Za-z]+Neural", result.voice):
            raise ValueError("Enter an Edge voice such as en-IE-EmilyNeural or en-GB-RyanNeural.")
        if not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z]{2,4})?", result.recognition_language):
            raise ValueError("Use a recognition language such as en-IN, en-US, or hi-IN.")
        if result.stt_provider not in {"auto", "google", "groq"}:
            raise ValueError("Choose Auto, Google or Groq speech recognition.")
        if result.voice_provider not in {"edge", "groq"}:
            raise ValueError("Choose Edge or Groq voice generation.")
        if result.groq_voice not in {"autumn", "diana", "hannah", "austin", "daniel", "troy"}:
            raise ValueError("Choose an available expressive Groq voice.")
        if any(type(getattr(result, name)) is not bool
               for name in ("speech_enabled", "wake_on_start", "start_with_windows")):
            raise ValueError("Speech, wake-at-start and Windows startup settings must be on or off.")
        if result.microphone_index is not None and (type(result.microphone_index) is not int or result.microphone_index < 0):
            raise ValueError("Choose a valid microphone.")
        if type(result.followup_seconds) is not int or not 0 <= result.followup_seconds <= 60:
            raise ValueError("Follow-up listening must be between 0 and 60 seconds.")
        return result

    def save(self, base_dir):
        from dotenv import dotenv_values, set_key
        base_dir = Path(base_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        values = asdict(self)
        values.pop("api_key")
        values.pop("persona")
        # Preserve the existing Spotify and other configuration entries.
        env_path = base_dir / ".env"
        existing = dotenv_values(env_path).get("GROQ_API_KEY", "") if env_path.exists() else ""
        if existing != self.api_key:
            set_key(str(env_path), "GROQ_API_KEY", self.api_key)
        atomic_json(base_dir / "settings.json", values)
