# Validation

## 9 September 2026: Windows startup and EXE release

- Before release publishing, both Windows x64 EXEs also passed an isolated first-user background UI launch with no API key, no local wake model, and Python removed from PATH. The temporary app-data folders were used and no bundled credential file appeared. These checks ran on the development PC, not a separate clean Windows installation.

- 111 automated tests passed independently in each repository using Python 3.12.
- Both rebuilt EXEs passed dependency/live AI checks and background UI smoke launches with exit code 0. All 16 packaged core modules in each EXE were compared with the final source and matched, including the startup module. The tested copies are in the Desktop `Fan Assistants Releases` folder.
- Startup tests exercised the real Windows registry API under isolated temporary test keys, covering enable/disable, independent persona entries, repeated disabling, moved launchers, removed entries and permission errors. Tests never registered either assistant in the actual Windows Run key.
- Additional coverage verifies quoted source/EXE launch commands, the Windows command-length limit, startup preference persistence, rollback after a failed settings save, and the Settings switch for both personas.
- Background launch remains withdrawn through the Tk startup callbacks and can be restored from the tray. A duplicate background launch does not signal the existing window to open.
- No reboot, sign-out, shutdown or sleep was performed during validation.

## 8 September 2026: Voice, actions and background operation

- 98 automated tests passed independently in each repository using Python 3.12.
- Both final executables passed dependency and live AI checks. Every packaged core module was compared with the current source and matched. FRIDAY was rebuilt with a clean cache after this comparison detected an older cached function.
- Final optimization disables drawing and telemetry polling for the hidden main window, releases the local wake model when idle with wake disabled, clears cancelled speech queues, and backs off failed speech providers.
- Coverage includes installed-app lookup, Store-app fallback, normal close requests, explicit power commands and cancellation, model-stream reconstruction, sentence speech ordering/prefetch, audio cleanup, microphone recovery, single-instance restore, tray commands and overlay states.
- Live Windows discovery found Spotify, Discord, Steam, Visual Studio Code and WhatsApp. Spotify resolved to its native executable.
- A generated speech sample triggered local FRIDAY wake detection at 0.896 seconds of audio. Groq Whisper correctly transcribed the generated command in 0.78 seconds. This is a synthetic regression check, not a measurement of every microphone or accent.
- Live conversation produced its first complete sentence at 2.72 seconds and completed the six-sentence answer at 2.98 seconds. Emma synthesis in a separate short sample received first audio at 1.56 seconds and completed in 2.67 seconds. Network timings vary; these are not end-to-end microphone-to-speaker guarantees.
- Closing the running FRIDAY window left its process alive. Launching again restored the same window. Further interactive desktop testing was stopped when the user pressed Escape.
- Power actions were tested with mocked Windows calls. Validation did not shut down, restart, lock or sleep the user's device.

Known limits: film-identical voices are not provided; online conversation, transcription and neural speech depend on provider/network availability. Wake capture pauses during assistant speech to avoid echo. Unregistered portable apps need a Start or desktop shortcut; ambiguous or elevated apps may need manual handling. The optional Groq expressive voice depends on account/model access.
