"""Local name detection. Only the subsequent request goes to online recognition."""
from collections import deque
import json
import os
import sys
from pathlib import Path

MODEL_NAME = "vosk-model-small-en-us-0.15"


def model_directory():
    personal = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "FanAssistants/speech-models" / MODEL_NAME
    bundled = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent)) / 'models' / MODEL_NAME
    return bundled if not (personal/'am/final.mdl').is_file() and (bundled/'am/final.mdl').is_file() else personal


class LocalWake:
    def __init__(self, persona, sensitivity=50):
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)
        self.name = "alfred" if persona == "alfred" else "friday"
        self.required_hits = 1 if sensitivity >= 75 else 2 if sensitivity >= 35 else 3
        self.hits = 0
        self.model = Model(str(model_directory()))
        self.recognizer = KaldiRecognizer(self.model, 16000, json.dumps([
            self.name, "hey " + self.name, "hello " + self.name, "okay " + self.name, "[unk]"
        ]))
        self.frames = deque(maxlen=100)  # two seconds of pre-roll at 320 samples

    def reset(self):
        self.recognizer.Reset()
        self.frames.clear()
        self.hits = 0

    def feed(self, data):
        self.frames.append(data)
        final = self.recognizer.AcceptWaveform(data)
        result = json.loads(self.recognizer.Result() if final else self.recognizer.PartialResult())
        text = result.get("text" if final else "partial", "").strip()
        if text in {self.name, "hey " + self.name, "hello " + self.name, "okay " + self.name}:
            self.hits += 1
            if final or self.hits >= self.required_hits:
                return list(self.frames)
        else:
            self.hits = 0
        if final:
            self.frames.clear()
        return None


class ReplayStream:
    def __init__(self, stream, frames):
        self.stream = stream
        self.frames = deque(frames)

    def read(self, size):
        return self.frames.popleft() if self.frames else self.stream.read(size)

    def close(self):
        return self.stream.close()
