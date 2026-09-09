# FRIDAY

FRIDAY is an independent Iron Man fan desktop assistant for Windows, with conversation, spoken replies, local wake detection and PC commands.

## Start

**Using the EXE:** double-click **FRIDAY.exe**. Python and Setup.bat are not required for the packaged app. Open **Settings** to add your own Groq API key and choose a microphone. Keep the EXE in a permanent folder before enabling Windows startup.

**Running from source:**

1. Install Python 3.12 and run **Setup.bat**. Setup installs dependencies and a 40 MB local wake model outside this folder.
2. Run **Start.bat**. Add a Groq API key in **Settings** for conversation. Local commands work without a key.
3. Select your actual microphone. **Auto** recognition uses Groq Whisper with Google fallback.
4. Enable **Wake word**, then say “Friday, open Spotify” or press **Talk**.

The wake switch is remembered. It defaults to off for a fresh installation. Run one assistant with wake enabled at a time.

## Background mode

Use **Hide to tray**, minimize, or close the window to keep it running. **Background.bat** starts in the tray. Launching again restores the existing window instead of starting another listener.

The tray menu has **Show**, speech mute, wake toggle and **Exit**. **Ctrl+Q** exits from the main window. A small blue FRIDAY indicator (gold for Alfred) pulses when the name is detected, changes during processing/speech, and fades after the exchange. Temporary microphone failures retry automatically.

In **Settings → Startup**, enable **Start with Windows** and click **Save** to launch quietly in the tray each time you sign in. Turn the switch off and save to remove automatic startup. This setting defaults to off and is independent for FRIDAY and ALFRED. Enable **Wake word** in the main window if you want voice activation after sign-in; that preference is remembered too.

Startup uses a per-user entry and needs no administrator access. If you separately disabled the assistant in **Windows Settings → Apps → Startup**, enable it there as well. After moving the EXE, open it from the new location once to update an existing startup entry. Launching a second background instance leaves the existing window hidden; double-clicking normally restores it. Startup happens after sign-in, following [Windows startup behavior](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys).

## Commands

- “Open Spotify”, “open Discord”, “open WhatsApp”, “open Visual Studio Code”, “list installed apps”.
- “Close Spotify” or “quit Discord”. This requests a normal close and permits save prompts. Ambiguous windows and protected system/assistant processes are not force-closed.
- “Shut down my computer”, “restart my laptop”, “put my device to sleep”, “lock my screen”. These have a ten-second countdown; say “cancel”, “cancel power action”, or press **Stop** to cancel. Shutdown does not force unsaved apps to close.
- “Volume 40 percent”, “mute”, “brightness 60 percent”, “system status”.
- “Open YouTube”, “open Spotify website”, “search the web for space news”, “weather in Mumbai”.
- “Take a note buy batteries”, “set a timer for five minutes”, “remind me tomorrow at 5 pm to call home”.
- “Remember that I am learning robotics”, “what do you remember about me?”, “take a screenshot”.

Apps come from Windows Start entries, Start/desktop shortcuts and App Paths. Unique short names can resolve longer installed-app names. Portable apps need a Start/desktop shortcut. Missing, ambiguous, elevated or unusual apps may need manual handling. Arbitrary shell commands are not executed. Power actions require direct user commands; model tool calls cannot trigger them.

Reminders run while the app is open; overdue reminders appear on the next launch.

## Speech

Replies stream into complete spoken sentences. Upcoming sentences render while the current sentence plays. Full replies stay onscreen; very long answers use a bounded spoken excerpt. **Esc** or **Stop** interrupts.

FRIDAY defaults to Emma neural speech; Emily offers an Irish accent, and Sonia a British accent. Alfred defaults to Ryan. Optional **Groq expressive voice** may require accepting the Orpheus model terms in your Groq account. Edge is the fallback, followed by Windows speech if online speech fails. This is not an exact reproduction of a film voice.

The local Vosk detector listens for the name without uploading idle room audio. Activated requests use online transcription. If the local model is missing, the app announces online wake fallback; rerun Setup to install the model. The app pauses capture while answering/speaking to avoid hearing itself, then allows 15 seconds of follow-up listening. Accuracy depends on the microphone, room noise and accent.

## Privacy and files

Private settings, keys, conversations, notes and reminders live outside this repository:

```text
%LOCALAPPDATA%\FanAssistants\FRIDAY\
```

Settings saves your Groq key there in `.env`. Advanced users can use `.env.example` as a template in that directory or set `GROQ_API_KEY`. Never commit real credentials. Groq receives conversation context and saved facts. Search queries go to the search provider; weather queries go to Open-Meteo.

Runtime environments and the wake model also live under Windows app data. This folder is independent of the other assistant's source.

## Validation and build

**Test.bat** runs regression tests with mocked device/network actions. **Check.bat** checks dependencies and makes a small live AI request. **Build.bat** creates:

```text
%LOCALAPPDATA%\FanAssistants\FRIDAY\build-output\dist\FRIDAY.exe
```

Distribute the built EXE as a GitHub Release asset. Each EXE includes its Python runtime and dependencies; credentials and user data are never bundled. The optional local wake model is installed separately by Setup.bat; without it the app announces online wake fallback.

With your own Python environment:

```powershell
python -m pip install -r requirements.txt
python setup_wake.py
python friday_app.py
python -m unittest discover -s tests -v
python -m pip install -r requirements-build.txt
python build_exe.py
```

Upload this folder's contents to a GitHub repository root. It contains source, setup scripts and tests; binaries, runtime environments, private data and keys stay outside it. The separate small English model uses Apache 2.0; see [Vosk models](https://alphacephei.com/vosk/models). This fan project is not affiliated with Marvel or DC.
