"""Turn model text deltas into bounded spoken sentences without repeating them."""
import re
from .voice import text_for_speech


class ReplySpeech:
    def __init__(self, speak):
        self.speak = speak
        self.buffer = ""
        self.started = False
        self.characters = 0
        self.capped = False
        self.in_code = False

    def feed(self, text):
        self.buffer += text
        while True:
            # Keep code intact until its closing fence so it is never read aloud.
            if "```" in self.buffer:
                start = self.buffer.index("```")
                end = self.buffer.find("```", start + 3)
                if end < 0:
                    if start:
                        self._say(self.buffer[:start])
                        self.buffer = self.buffer[start:]
                    return
                self.buffer = self.buffer[:start] + " I've put the code in the conversation. " + self.buffer[end + 3:]
            match = re.search(r"[.!?](?:[\"')\]]?)(?=\s)", self.buffer)
            if not match:
                # Long sentences may begin after a clause, but never split a URL.
                match = re.search(r"[,;:]\s", self.buffer[100:200]) if len(self.buffer) > 210 else None
                if match:
                    end = 100 + match.end()
                else:
                    return
            else:
                end = match.end()
            self._say(self.buffer[:end])
            self.buffer = self.buffer[end:].lstrip()

    def _say(self, text):
        if self.capped:
            return
        text = text_for_speech(text)
        if not text:
            return
        remaining = 1325 - self.characters
        if len(text) > remaining:
            if remaining > 60:
                text = text[:remaining].rsplit(" ", 1)[0]
            else:
                text = ""
            text += " The rest is in the conversation."
            self.capped = True
        self.characters += len(text)
        self.started = True
        self.speak(text)

    def finish(self):
        if self.buffer.strip():
            text = self.buffer.split("```", 1)[0] if self.buffer.count("```") % 2 else self.buffer
            self._say(text)
        self.buffer = ""
