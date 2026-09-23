# Validation

## 23 September 2026: version 5 and publisher verification

- **136 automated tests passed independently in each repository** with Python 3.12 on Windows. Coverage includes streaming cancellation, partial transcription, spoken corrections, microphone reconnection, calibrated settings, action verification, app context, routines, cancellation between requests, update origin/checksum validation and the pinned publisher key.
- A real synthesized MP3 was fed incrementally through the native miniaudio decoder into a silent test output. PCM playback began before the last simulated network packet; no microphone or speaker was used. Native WebRTC processing accepted the expected capture and playback frame formats.
- All **22 packaged core modules and each persona's launcher** matched the final source in both directory payloads and both portable EXEs. A stale cached module found during packaging was rebuilt before release.
- All four packages passed isolated first-user native dependency and background UI checks with no API key and no Python on PATH. The installed payloads loaded their bundled English model. Diagnostics reported the correct persona, original repository and publisher-key fingerprint. No credential file was created.
- Both final Setup EXEs were actually installed into isolated temporary directories, checked for native dependencies/model and hidden UI launch, and uninstalled successfully. Existing Windows startup values were preserved, and the temporary uninstall registrations were removed. Tests ran on the development Windows PC, not a separate clean Windows machine.
- Settings and diagnostics identify `lkghost327-afk`; the installer identifies the same publisher. Releases include a pinned RSA-3072 public key, SHA-256 asset hashes and a signed manifest. The private signing key is protected for the publisher's Windows account outside the repositories and build payloads. See [verification instructions](../OWNERSHIP.md).
- No shutdown, sleep, restart or sign-out was performed. Tests did not close the user's real applications or change their startup preferences.

Version 5 limits: physical microphone/accent accuracy and speaker echo cancellation still need tuning on each PC. Spoken interruption is supported during streaming Edge speech with the local model; buffered Groq/Windows fallback pauses capture. Local recognition is English; Auto uses local partial previews but still sends a completed utterance for final cloud transcription. Windows UI Automation works only with accessible, unambiguous controls and normal permitted windows. The fan voices are not film-identical. Online availability and latency vary. Release signatures do not make these builds Windows Authenticode-signed.

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

Version 4 limits (some superseded by version 5): film-identical voices are not provided; online conversation, transcription and neural speech depend on provider/network availability. Wake capture pauses during assistant speech to avoid echo. Unregistered portable apps need a Start or desktop shortcut; ambiguous or elevated apps may need manual handling. The optional Groq expressive voice depends on account/model access.
