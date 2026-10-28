"""Local name detection. Only the subsequent request goes to online recognition."""
from collections import deque
import json
import re
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
        self._decoder = KaldiRecognizer
        # A tiny grammar can force unrelated speech into a name. An unrestricted
        # recognizer must also hear the name at the beginning of the utterance.
        self.aliases = ['friday', 'fry day'] if self.name == 'friday' else ['alfred', 'al fred']
        name_pattern = '(?:' + '|'.join(re.escape(name) for name in self.aliases) + ')'
        self.prefix = re.compile(r'^(?:(?:hey|hi|hello|okay|ok)\s+)?' + name_pattern + r'\b', re.I)
        self.verified_prefix = re.compile(r'^(?:oh\s+)?(?:(?:hey|hi|hello|okay|ok|a)\s+)?' + name_pattern + r'\b', re.I)
        self.frames = deque(maxlen=150)  # Three seconds; retain audio while decoders settle.
        self.reset()

    def reset(self):
        # Reset() alone retains decoder adaptation from a cut-short wake phrase.
        # Fresh decoders reuse the expensive model without inheriting stale words.
        grammar = [prefix + name for name in self.aliases for prefix in ('', 'hey ', 'hello ', 'okay ')]
        self.recognizer = self._decoder(self.model, 16000, json.dumps(grammar + ['[unk]']))
        self.verifier = self._decoder(self.model, 16000)
        self.frames.clear()
        self.hits = 0
        self._audio_seconds = 0.0
        self._candidate_until = -1.0
        self._verified_until = -1.0

    def feed(self, data):
        self.frames.append(data)
        self._audio_seconds += len(data) / 32000.0
        final = self.recognizer.AcceptWaveform(data)
        verified_final = self.verifier.AcceptWaveform(data)
        verified = json.loads(self.verifier.Result() if verified_final else self.verifier.PartialResult())
        verified_text = verified.get('text' if verified_final else 'partial', '').strip()
        verified_match = bool(self.verified_prefix.match(verified_text))
        if verified_final:
            self._verified_until = self._audio_seconds + 1.2 if verified_match else -1.0
        verified_done = self._audio_seconds <= self._verified_until
        result = json.loads(self.recognizer.Result() if final else self.recognizer.PartialResult())
        text = result.get("text" if final else "partial", "").strip()
        if self.prefix.match(text.removeprefix('[unk] ').strip()):
            self._candidate_until = self._audio_seconds + 1.2
        candidate = self._audio_seconds <= self._candidate_until
        if candidate and (verified_match or verified_done):
            self.hits += 1
            if verified_done or self.hits >= self.required_hits:
                return list(self.frames)
        else:
            self.hits = 0
        if final and not candidate and not verified_done:
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
