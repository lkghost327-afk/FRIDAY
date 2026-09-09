"""Small, explicit, per-persona memory; no background file or clipboard indexing."""

import json
from pathlib import Path
import threading

from .settings import atomic_json


class Memory:
    def __init__(self, base_dir):
        self.path = Path(base_dir) / "data" / "assistant_state.json"
        self._lock = threading.RLock()
        self.history = []
        self.facts = []
        self.warning = ""
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.facts = [x[:1000] for x in data.get("facts", []) if isinstance(x, str)][:100]
                raw = data.get("history", [])
                # Only complete user/assistant pairs may go back to the model.
                for i in range(0, len(raw) - 1, 2):
                    user, answer = raw[i:i+2]
                    if (isinstance(user, dict) and isinstance(answer, dict)
                            and user.get("role") == "user" and answer.get("role") == "assistant"
                            and isinstance(user.get("content"), str) and isinstance(answer.get("content"), str)):
                        self.history.extend([{"role": "user", "content": user["content"][:8000]},
                                             {"role": "assistant", "content": answer["content"][:12000]}])
                self.history = self.history[-24:]
            except (OSError, ValueError, AttributeError, TypeError):
                self.warning = "Saved conversation could not be read. A fresh session is available; the original file is preserved."
                self.path = self.path.with_name("assistant_state_recovered.json")

    def snapshot(self):
        with self._lock:
            return [dict(m) for m in self.history], list(self.facts)

    def _save(self):
        atomic_json(self.path, {"version": 1, "facts": self.facts, "history": self.history})

    def add_turn(self, user, answer):
        with self._lock:
            self.history.extend([{"role": "user", "content": user}, {"role": "assistant", "content": answer}])
            self.history = self.history[-24:]
            self._save()

    def remember(self, fact):
        fact = fact.strip()[:1000]
        if not fact:
            return "Tell me what you would like me to remember."
        with self._lock:
            if fact.casefold() not in {f.casefold() for f in self.facts}:
                self.facts = (self.facts + [fact])[-100:]
                self._save()
        return "I'll remember: " + fact

    def forget(self, query):
        with self._lock:
            old = len(self.facts)
            self.facts = [f for f in self.facts if query.casefold() not in f.casefold()]
            self._save()
            return f"Removed {old - len(self.facts)} matching saved memories."

    def clear_history(self):
        with self._lock:
            self.history = []
            self._save()

    def clear_facts(self):
        with self._lock:
            self.facts = []
            self._save()
