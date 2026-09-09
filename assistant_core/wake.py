"""Local name detection. Only the subsequent request goes to online recognition."""
from collections import deque
import json
import os
from pathlib import Path

MODEL_NAME = "vosk-model-small-en-us-0.15"


def model_directory():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "FanAssistants/speech-models" / MODEL_NAME


class LocalWake:
    def __init__(self, persona):
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)
        self.name = "alfred" if persona == "alfred" else "friday"
        self.model = Model(str(model_directory()))
        self.recognizer = KaldiRecognizer(self.model, 16000, json.dumps([
            self.name, "hey " + self.name, "hello " + self.name, "okay " + self.name, "[unk]"
        ]))
        self.frames = deque(maxlen=64)  # two seconds of pre-roll at 512 samples

    def reset(self):
        self.recognizer.Reset()
        self.frames.clear()

    def feed(self, data):
        self.frames.append(data)
        final = self.recognizer.AcceptWaveform(data)
        result = json.loads(self.recognizer.Result() if final else self.recognizer.PartialResult())
        text = result.get("text" if final else "partial", "").strip()
        if text in {self.name, "hey " + self.name, "hello " + self.name, "okay " + self.name}:
            return list(self.frames)
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
