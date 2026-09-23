# Included components

This fan project is independent of Marvel, DC, Microsoft and Samsung.

The installer includes the Python runtime and dependencies pinned in requirements.txt.
PyInstaller collects package metadata and native library files with the payload.

The bundled English wake/transcription model is **vosk-model-small-en-us-0.15**
from https://alphacephei.com/vosk/models, licensed under Apache License 2.0.
Model files are redistributed without modification. See the model's README and
https://www.apache.org/licenses/LICENSE-2.0 for its license.

Vosk: https://github.com/alphacep/vosk-api (Apache 2.0).
miniaudio: https://github.com/irmen/pyminiaudio (MIT; bundled miniaudio public domain or MIT).
WebRTC audio processing wrapper: https://pypi.org/project/aec-audio-processing/ (BSD 3-Clause).
pywinauto: https://github.com/pywinauto/pywinauto (BSD 3-Clause).
Inno Setup: https://jrsoftware.org/isinfo.php (installer compiler; see its distribution license).

Cloud speech and AI services are not bundled models. Their availability, terms and
account requirements are controlled by their providers. Each user supplies their
own optional Groq key. No developer credentials are included in any release.
