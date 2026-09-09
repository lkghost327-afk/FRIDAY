# FRIDAY: first run on Windows

## Download and launch

1. Use Windows 10 or 11, 64-bit (x64). These builds are for Windows desktop PCs.
2. Download **FRIDAY.exe** from this repository's Releases page. The GitHub source-code ZIP is for development; it is not the app download.
3. Save the EXE in a permanent folder and double-click it. Python is included. A first launch can take a few seconds while the bundled files unpack.
4. Open **Settings**, select your actual microphone, and click **Save**. Allow desktop apps to use your microphone in Windows Settings if access is blocked.

These builds are not code-signed. Windows may show an unknown-publisher warning. The release includes SHA256SUMS.txt so you can check that the downloaded file matches the published build using PowerShell:

```powershell
Get-FileHash .\FRIDAY.exe -Algorithm SHA256
```

## Conversation and voice

For AI conversation, create your own key in the [Groq console](https://console.groq.com/keys), paste it into **Settings → Groq API key**, and Save. No shared API key is bundled. Use the default **auto** conversation model and **edge** voice provider to begin. Conversation, request transcription and neural speech require an internet connection; provider availability and account limits affect response speed.

Try typing **what time is it** or **open Notepad** first. Local PC commands work without an AI key. Then press **Talk** and say a request. Enable **Wake word** to call “Friday” before a question. For reliable capture, run one assistant with wake listening enabled at a time. Wake listening pauses during replies to avoid feedback from the speaker.

## Optional local wake detection, without installing Python

The EXE includes the speech engine, but the separate 40 MB wake model is optional. Without it, the app announces online wake fallback.

1. Download [vosk-model-small-en-us-0.15.zip](https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip) from the official Vosk site.
2. Extract it and place the whole **vosk-model-small-en-us-0.15** folder under `%LOCALAPPDATA%\FanAssistants\speech-models\`. You can paste that parent path into File Explorer and create the folders if needed.
3. Check that this file exists, without an extra nested model folder:

```text
%LOCALAPPDATA%\FanAssistants\speech-models\vosk-model-small-en-us-0.15\am\final.mdl
```

4. Exit the assistant using the tray menu and launch it again. Both assistants can use the same model installation.

The [Vosk model list](https://alphacephei.com/vosk/models) lists this model under Apache 2.0. Source users can instead run Setup.bat to install it automatically.

## Background and Windows startup

Closing or minimizing the window keeps the assistant running in the tray. Use **Show** in the tray menu, or double-click the EXE again, to restore it. Use tray **Exit** or **Ctrl+Q** to quit completely.

To start after Windows sign-in, enable **Settings → Startup → Start with Windows** and Save. Turn the same setting off and Save to disable automatic startup. Enable the separate **Wake word** switch if you want it to listen after sign-in. Both settings default to off for a new user. If the EXE is moved after enabling startup, launch it from the new location once.

## If something is not working

- **No AI reply:** check the key, internet connection and Groq account availability. Local commands still work without a key.
- **Cannot hear you:** choose the correct input device, check Windows microphone access, and test with Talk before using the wake word.
- **No speech:** enable spoken replies, check the output volume/device, and use Settings → Test saved voice. Edge is the default; optional Groq expressive speech may require accepting model terms in your account.
- **Cannot find a portable app:** add a Start-menu or desktop shortcut for it. Ambiguous, elevated or unusual apps may need manual handling.

Settings, keys and personal history are stored in `%LOCALAPPDATA%\FanAssistants\FRIDAY\`, separately from the EXE. Moving or updating the EXE keeps those settings.

Validation covered fresh-user packaged launches on the development Windows PC, existing automated action/audio/tray tests, and live AI checks. It does not guarantee identical microphone recognition, network latency or compatibility with every PC.
