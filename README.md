# FRIDAY

An independent Iron Man fan assistant for Windows: natural conversation, streamed speech, local wake detection and useful PC controls.

**[Download FRIDAY-Setup.exe](https://github.com/lkghost327-afk/FRIDAY/releases/latest/download/FRIDAY-Setup.exe)** · [Portable EXE](https://github.com/lkghost327-afk/FRIDAY/releases/latest/download/FRIDAY.exe) · [First-run guide](docs/FIRST_RUN.md) · [All releases](https://github.com/lkghost327-afk/FRIDAY/releases) · [ALFRED](https://github.com/lkghost327-afk/ALFRED)

## Start on Windows

1. Download **FRIDAY-Setup.exe** for Windows 10/11 x64. It includes Python, dependencies and the English speech model. Install for your Windows account; administrator access is not required.
2. Launch FRIDAY. Settings opens on first use. Choose your microphone, save, then use **Test / calibrate saved microphone** and stay quiet for two seconds.
3. Add your own [Groq API key](https://console.groq.com/keys) for AI conversation. Local typed PC commands work without a key. Choose **local** recognition for English voice commands without uploading the recording.
4. Press **Talk**, or enable **Wake word** and say “Friday, open Spotify”. Only enable wake listening in one assistant at a time.

The optional portable EXE needs no Python installation. Its first run downloads the speech model, or use **Settings → Install local wake model**. Keep it in a permanent folder if enabling startup. Releases are unsigned; SHA256SUMS.txt is provided for checking downloads. Download a release asset, not GitHub’s source-code ZIP.

## What is new in version 5

- **Streaming speech:** Edge audio is decoded and played as chunks arrive. Local English transcription shows words while you speak; Auto uses this preview and then cloud transcription for the final request.
- **Spoken interruptions:** say “stop” or begin a correction during streaming Edge speech. WebRTC echo cancellation uses the actual playback signal. A local speech model is required; buffered Groq/Windows fallback pauses capture while playing.
- **Microphone tuning:** noise reduction, quiet-room calibration, wake sensitivity, pause duration and echo delay. A disconnected named microphone falls back to the Windows default and is rediscovered on the next capture after reconnection.
- **Verified PC actions:** opening/closing apps checks their visible windows; unconfirmed launches and remaining save dialogs are reported honestly. Minimize, maximize, restore and focus check the resulting window state.
- **In-app actions:** native Spotify search plus accessible search fields and exact-name buttons through Windows UI Automation. Unsupported, ambiguous or protected controls are rejected.
- **Context and routines:** say “minimize it” after naming an app. Context expires after five minutes. Save up to 30 routines with at most eight supported steps; Stop cancels remaining steps.
- **Installation and maintenance:** model included with the installer, first-use Settings, per-user uninstall, manual update checks and checksum-verified installer downloads. Hidden UI work is reduced; Diagnostics reports bounded latency samples and current process CPU/RAM.

## Commands

- “Open Spotify”, “open Discord”, “open WhatsApp”, “open Visual Studio Code”, “list installed apps”.
- “Close Spotify”, “minimize it”, “maximize Notepad”, “restore Notepad”, “focus Notepad”. Closure uses normal Windows close requests and allows unsaved-work prompts.
- “Search Spotify for jazz”, “list buttons in Spotify”, “press Play in Spotify”. Button names must match accessible controls in that app. Sending, deleting, purchasing and similar consequential buttons are excluded.
- “Create routine work: open Notepad; volume 30”, then “run routine work” or “start work”. Use “list routines” or “delete routine work” to manage saved routines. Supported steps: open, window controls, volume and brightness.
- “Shut down my computer”, “restart my laptop”, “put my device to sleep”, “lock my screen”. A ten-second countdown allows **Stop** or “cancel power action”. Power actions require a direct request and never force-close unsaved apps.
- “Volume 40 percent”, “mute”, “brightness 60 percent”, “system status”, “take a screenshot”.
- “Open Spotify website”, “search the web for space news”, “weather in Mumbai”.
- “Take a note buy batteries”, “set a timer for five minutes”, “remind me tomorrow at 5 pm to call home”.
- “Remember that I am learning robotics”, “what do you remember about me?”

App discovery uses Windows Start entries, Start/desktop shortcuts and App Paths. Portable apps need a registered shortcut. Some Store apps, elevated windows and apps without accessible controls require manual handling. Arbitrary shell commands are not executed. Reminders run while the assistant is open; overdue reminders appear next launch.

## Tray, startup and indicator

Minimizing, closing the window or **Hide to tray** keeps the assistant running. Double-click its EXE again or use tray **Show** to restore the existing instance. Tray **Exit** or **Ctrl+Q** quits completely. A small animated blue indicator shows wake detection, listening, processing and speech.

Enable **Settings → Start with Windows**, then Save, to start quietly after Windows sign-in. Disable the same setting to remove startup. Wake listening has its own remembered switch. Both default off for a new user. Windows’ own Startup Apps setting must also permit launch. Uninstall removes a startup entry only when it points to that installation; personal settings and history remain.

## Voice and privacy

Default neural voices are Emma for FRIDAY and Ryan for ALFRED. Optional Groq expressive speech depends on your account/model access. Online speech falls back to Windows speech when available. These are fan-inspired voices, not exact film voice reproductions.

With the local model, idle wake audio stays on the PC. **Local** transcription is English and stays local; **Auto/Groq/Google** send activated requests to the chosen service. If the wake model is unavailable, online wake fallback is announced. AI conversation and neural speech require internet access. Microphone accuracy, echo cancellation and response speed depend on hardware, room acoustics, accent and network conditions.

Private keys, settings, history, notes, reminders and routines are stored outside the repository in `%LOCALAPPDATA%\FanAssistants\FRIDAY\`. Your Groq key is saved in that folder’s `.env`; no developer key is bundled. Groq receives conversation context and saved facts. Search queries go to the search provider; weather uses Open-Meteo. Diagnostics collects timing/counters rather than recordings or transcripts.

## Development and validation

Use Python 3.12 on Windows. **Setup.bat** installs dependencies and the local model; **Start.bat** launches; **Background.bat** starts in the tray; **Test.bat** runs the regression suite. **Check.bat** also checks the live AI connection.

```powershell
python -m pip install -r requirements.txt
python setup_wake.py
python friday_app.py
python -m unittest discover -s tests -v
python -m pip install -r requirements-build.txt
python build_exe.py
python build_installer.py
```

Installer builds require [Inno Setup 6](https://jrsoftware.org/isinfo.php). Pass `--iscc` to specify its compiler. Build output stays outside Git under `%LOCALAPPDATA%\FanAssistants\FRIDAY\build-output\dist\`.

Use `FRIDAY.exe --check-offline --report diagnostics.json` to check native libraries and the speech model without microphone capture, playback or network access. See [validation results](docs/VALIDATION.md), [architecture](docs/ARCHITECTURE.md) and [third-party notices](docs/THIRD_PARTY.md). Physical microphone quality and support for arbitrary applications are not guaranteed by automated tests.

## Publisher verification

Original publisher: **lkghost327-afk**. The app identifies its publisher in Settings and diagnostics. Releases include an RSA-signed manifest and a pinned public-key verifier. See [ownership and verification](OWNERSHIP.md).
