# v5.1 beta validation

Status: beta software/package validation complete. Real-device acceptance remains open; do not treat this beta as a completed hardware qualification.

## Implemented

- Optional Deepgram Nova-3 WebSocket transcription with display-only interim text, bounded buffering, cancellation and an acknowledged final result. Credentials stay in personal `.env` files. No live Deepgram account test has been completed yet.
- Hindi (`hi-IN`) and Hindi/English automatic recognition (Groq language detection or Deepgram `multi`). Hindi/Hinglish command parsing routes through the same validated tools. Hindi replies choose Swara/Madhur; local Vosk recognition and spoken interruptions remain English-only.
- Local wake confirmation checks that a full-vocabulary decoder hears an assistant name at the beginning. Fresh decoders reuse the model and avoid stale text from an earlier, interrupted utterance. Missing wake models never cause online standby uploads.
- Next-segment audio preparation, cancellable network tasks and transcript-free playback-stop timing.
- UI Automation in a killable process; PID, process start time and window identity checks; cancellation/timeouts terminate the worker. An action already accepted by an app cannot be undone by cancelling afterward.
- Numbered window selection; Spotify player controls separated from album buttons; browser/Explorer/Notepad navigation and search adapters. Unsupported controls fail with a specific explanation. These adapters require real app testing across versions and display languages.
- Spotify-specific Windows media-session selection and idempotent play/pause, with bounded awaits and no global-player fallback. The development PC's Spotify session was detected as paused; its minimized/restored accessibility tree did not expose player or song controls.
- Native Windows audio/power notifications, cancellation of stale requests on recovery, and a guided setup with local microphone levels/calibration and voice previews.
- Pinned publisher-signature verification in update checks and download/launch validation; settings checkpoint and incomplete-update recovery. Stable updates remain opt-in and prereleases are excluded.

## Measurements performed on the development PC

The repeatable benchmark uses eight generated SAPI phrases at quiet, 20 dB and 10 dB signal-to-noise conditions: 24 cases, with the exact saved WAV corpus reused for both versions. It never captures a microphone or controls an app. v5 produced five errors; the revised v5.1 detector produced one missed ALFRED wake at 10 dB and no false activations in this small corpus. This does not establish real-room accuracy or accent coverage. Additional recognition increases CPU work; measure it on the target PC.

Silent Edge decode checks produced first PCM in roughly 0.45–3.11 seconds in the measured run. The first voice includes cold imports/network costs. These are isolated samples, not a guaranteed improvement or an end-to-end microphone-to-speaker result. Decoder cancellation reached 63 ms in the latest synthetic run; audible interruption still requires hardware validation.

A five-minute isolated idle-tray soak exposed growing Windows handle usage during repeated PortAudio enumeration. Replacing polling with native notifications stopped that growth in a second five-minute run: handles settled from 440 to 429; RAM after startup stayed around 83–84 MB. This is an idle UI/device-monitor test with microphone and cloud calls disabled, not the planned eight-hour voice soak.

The signed updater successfully authenticated the existing public v5.0.0 manifests from both original repositories without downloading or launching their installers.

Both repositories passed 165 automated tests, including Hindi/Hinglish routing, app focus loss, ambiguous Spotify controls, exact media-session selection, cancellation, streaming protocol handling, update tampering and both personas' setup/settings UI. Full first-run setup verifies the user's Groq key before completion; limited offline mode is an explicit alternative. The portable app does not download a speech model automatically. A live synthetic Hindi sample generated with Edge Swara was transcribed by Groq Whisper in both explicit Hindi and automatic-language modes as “स्पोटिफाई खोलो, आवाज कम करो, आज मौसम कैसा है?”. This tests provider integration, not real microphone/accent accuracy. No spoken command from this check was executed.

All four packaged executables matched the final source for all 28 `assistant_core` modules plus the correct persona launcher. Each installer payload and portable EXE passed native dependency, media-worker and hidden-UI checks in a fresh profile with no key and no system Python on `PATH`. Neither repository nor package contained an `.env`, settings file or personal data.

Both final installers passed an isolated fresh install, launch and uninstall. Each also upgraded an isolated public v5.0.0 installation to v5.1.0-beta.1, preserved settings, notes and credential-file bytes, reported the beta version, launched native diagnostics/UI and uninstalled without changing the pre-test Windows startup state. A deliberately over-deep test path hit Windows' legacy path limit and rolled back cleanly; the normal short per-user path passed.

## Real-device acceptance still to verify

- Real Hindi/Hinglish speech and optional Deepgram streaming with a user-configured account.
- Real Spotify controls and search results; browser/Explorer/Notepad versions and multiple windows.
- Microphone unplug/reconnect, Bluetooth changes, speaker echo and interruption, Windows sleep/resume and actual sign-in startup.
- Eight-hour background voice soak and a separate clean Windows environment.

Stable promotion stays blocked until these acceptance checks are complete. Existing v5.0.0 remains the stable release; v5.1.0-beta.1 is published as a prerelease with a signed manifest tied to its source commit.

## Repeatable tools

Run `python tools/benchmark.py --corpus C:\path\to\synthetic-corpus --output C:\path\to\report.json`; add `--online` for silent Edge voice timing. `--source-tree` compares a separately extracted source release against the same corpus.

Run `python tools/soak.py --seconds 28800 --output C:\path\to\soak.json` for an isolated idle-tray soak. It creates temporary settings and does not alter your actual startup preferences, record audio or execute PC commands. `python tools/probe_app.py Spotify` reads accessible controls; review its visible-app labels before sharing the output.

## Provider and signing references

[Deepgram live protocol](https://developers.deepgram.com/reference/speech-to-text/listen-streaming), [Hindi/multilingual support](https://developers.deepgram.com/docs/models-languages-overview), [Groq transcription](https://console.groq.com/docs/speech-to-text).

The existing RSA release identity is retained. Windows Authenticode remains separate and requires publisher identity/certificate or an eligible signing service; no signing service or subscription was purchased. See [Microsoft's code-signing options](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options).
