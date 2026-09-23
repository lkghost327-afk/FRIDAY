# FRIDAY: first run on Windows

1. Download **FRIDAY-Setup.exe** from [FRIDAY Releases](https://github.com/lkghost327-afk/FRIDAY/releases). Use Windows 10/11 x64. The installer includes Python and the English wake/transcription model and runs without administrator access.
2. Launch FRIDAY. First-use Settings asks for a microphone and an optional Groq key. Local PC commands do not need an AI key; conversation requires your own key from https://console.groq.com/keys.
3. Select the microphone and Save, then reopen Settings and run **Test / calibrate saved microphone** while staying quiet for two seconds. Allow desktop microphone access in Windows Settings if needed.
4. Try typing “open Notepad”, then use **Talk**. Choose **local** recognition for local English transcription, or **auto** for a local preview followed by cloud recognition. Enable **Wake word** to say “Friday” before requests.
5. Default Edge speech streams as it arrives. With the local model, say “stop” or a correction during playback. Tune wake sensitivity, request pause and echo delay if needed. **Esc** and **Stop** also cancel.

## Portable version

Download **FRIDAY.exe** if you prefer a single file. Keep it in a permanent folder. Python is included; the wake model downloads in the background on first normal launch. You can also select **Settings → Install local wake model**. This requires internet access and about 40 MB of download. The installer already includes the model.

The model can be installed manually from https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip. Extract its named folder beneath `%LOCALAPPDATA%\FanAssistants\speech-models\`. There must be an `am\final.mdl` inside that model folder.

## Background, startup and updates

Close/minimize keeps the assistant in the tray. Double-click its EXE or use tray **Show** to restore it. Tray **Exit** or **Ctrl+Q** quits completely. Only enable wake listening in one assistant at a time.

**Settings → Start with Windows → Save** enables launch after sign-in; disable and Save to remove it. Enable **Wake word** separately if desired. Both default off. After moving a portable EXE, launch it from the new location once to refresh startup.

**Check for updates** looks for a newer stable GitHub Release. **Download verified update** checks the published SHA-256 and size, then asks whether to run the installer. The application exits before installation. Updates are never installed automatically. Uninstall through Windows Apps; personal settings/history are retained in `%LOCALAPPDATA%\FanAssistants\FRIDAY\`.

## Troubleshooting

- No AI reply: check your key, internet and Groq account access. Local commands remain available.
- Poor recognition: save the correct input device, calibrate it, try a headset and adjust the request pause. Local recognition supports English; online recognition supports the configured language.
- Spoken interruptions trigger incorrectly: use a headset, tune echo delay, or disable **Allow spoken interruptions**. Buffered Groq/Windows speech pauses capture while playing.
- No speech: enable spoken replies, check output volume and use **Test saved voice**. Online services can be unavailable; the app attempts fallbacks.
- App action unconfirmed: check the app’s window or save dialog. Add a Start/desktop shortcut for portable apps. UI Automation depends on the app exposing accessible controls.
- Setup/update failed: check internet access and use Releases to download manually. An incomplete manually installed model folder should be renamed before retrying model setup.

Releases are unsigned. Compare `Get-FileHash .\FRIDAY-Setup.exe -Algorithm SHA256` with **SHA256SUMS.txt** in the release. See [validation and limitations](VALIDATION.md) for the checks performed.

## Publisher verification

The original publisher is lkghost327-afk. Download all release assets to one folder and run Verify-Release.ps1 from the original repository to verify the pinned publisher key, signed manifest and file hashes. See [ownership verification](../OWNERSHIP.md).
