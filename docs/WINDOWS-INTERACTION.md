# Windows interaction — 5.1.0-beta.4

Both assistants share independently implemented Windows controls and keep their own personas, credentials and settings.

## Talk and direct dictation

Enable Global voice shortcut in Settings. Ctrl+Alt+F talks to FRIDAY; Ctrl+Alt+A talks to ALFRED. Add Shift to dictate into the focused app field. Choose Hold (release to send), Toggle (press again to send), or Pause (finish after silence) in Settings. During an answer the shortcut stops it. Escape cancels while the shortcuts are enabled, including from another app. These work while minimized to the tray; Exit unregisters them.

Say “dictate in Notepad”, or use Dictate and name an app. Click the intended text field first when an app has several. The window and field are bound before listening. The final transcript is inserted literally: command-like phrases and key-looking text do not execute. There is no clipboard replacement, Enter key or message submission.

Insertion uses the caret/selection when Windows exposes a consistent selection; otherwise the assistant announces that it will append. Password, read-only, ambiguous, changed or expired targets are rejected. Insertion is verified, never automatically retried. If uncertain, recover the words from the preview after checking the app. Editors without a writable accessibility value are unsupported. Limits: 50,000-character field, 8,000-character utterance, 30-second pause-mode or 60-second manual capture window. Hitting the limit opens a review instead of inserting or executing the transcript.

Hindi and English follow your recognition service and language settings. No model is downloaded automatically. Provider latency and microphone quality still affect results.

## Screen answers and app context

“Look at my screen and explain this error” or “What is on my screen?” sends one primary-screen image to Groq using your own key and configurable vision model. This happens only on an explicit screen question. Images remain in memory; screen questions and answers are not saved in history. The answer remains visible in the current session. Provider processing and charges apply.

The image request has no action tools, so instructions in an image cannot dispatch app operations. It sees one snapshot, not a live view. The default vision model follows https://console.groq.com/docs/vision; Settings accepts another model available to your account.

“Read text in Chrome” remains a local accessible-text preview. For requested app tasks, the model can inspect bounded accessible text and exact button labels; these results enter that AI request. Editable values and password subtrees are excluded from the text reader. Multiple windows require a choice from “list windows in Chrome”. App controls use isolated workers, deadlines, cancellation and window/process identity checks.

## Commands and saved phrases

- open Notepad then volume 30
- when I say work, open Notepad then volume 30
- work / start work / run routine work
- list routines / delete routine work

Saved phrases match exactly. All steps validate before starting. Eight steps maximum: opening apps, named-window controls, volume and brightness. Cancellation or an unconfirmed outcome stops the sequence. Reported device levels must match requested values. Model-driven tasks use a closed tool set with bounded rounds and duplicate-action prevention. Neither path executes arbitrary shell text or guesses click coordinates.

## Verification boundaries

Tests cover literal Unicode insertion, changed-field rejection, cancellation, explicit screenshot routing, tools-disabled vision, local preview privacy and shortcut cleanup. This does not establish universal app compatibility, live microphone accuracy or complete feature parity with another desktop product. Arbitrary visual clicking, screen drawing, long-form recording and third-party account connectors are not implemented here.

## Voice and interface update

The default window is compact. Expand restores the dashboard. The live caption shows provisional words, and the meter shows microphone level. The corner indicator shows the current phase and partial text without taking focus. Up in an empty composer recalls the last typed request. Double-click a prior request to edit it or an answer to copy it.

Phrase detection uses raw audio and keeps 400 ms before onset. Its threshold adapts only before speech and then stays fixed. A brief click is insufficient to start a phrase. The default pause is 0.95 seconds; explicitly saved pause values remain unchanged. Normalization boosts quiet cloud utterances at most fourfold with a peak limit. Optional noise reduction runs after capture for buffered cloud requests, with a guard against erasing quiet speech; echo processing also supports spoken interruption.

Settings offers whisper-large-v3 (accuracy) and whisper-large-v3-turbo (speed), both cloud services, plus a Test this API key button. A rejected key produces a specific notice; it does not send that failed recording to another provider. Tests and feature boundaries are listed in DESKTOP-COVERAGE.md.

## Wake reliability update

The compact window exposes the same wake switch as the dashboard and tray. Local recognition accepts the assistant name at the start of an utterance, including “fry day” and “al fred”. Two decoders still verify a wake; they may finish up to 1.2 seconds apart. Up to three seconds of audio is retained while they settle, so an immediate command is not discarded. If the detector cannot load, standby reports the problem and stops reopening the microphone repeatedly. Talk remains available; toggle wake off/on to retry.

Offline checks cover both decoder completion orders, expired candidates, unrelated speech, sensitivity and reset. The existing Vosk model also passed 14 synthetic Windows-speech cases (both names and negative phrases). Synthetic speech does not establish accuracy for your voice, room or laptop microphone.
