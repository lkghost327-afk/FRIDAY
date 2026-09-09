# Architecture

`assistant_core/ui.py` renders the native CustomTkinter interface and consumes a thread-safe event queue. Network, microphone and action work run outside the Tk main thread.

`controller.py` coordinates one conversation worker with the voice service. `voice.py` owns the microphone and speech queue, preserves inline wake commands, and invalidates old generations when interrupted. Capture is gated until model work and speech finish.

`brain.py` discovers available Groq models, manages bounded tool rounds and supplies actual tool results to the conversation. `actions.py` validates closed tool schemas and provides supported PC actions, weather/search, notes and persistent reminders. Arbitrary shell execution is not supported.

`settings.py` and `memory.py` provide per-assistant configuration and atomic persistence. `app.py` locates Windows app data independently of the source folder or executable location. This keeps secrets and personal history out of the GitHub checkout.

`build_exe.py` packages only this repository's entry point and required dependencies. It does not require the other assistant's folder. Build output is stored in Windows app data.

`lifecycle.py` uses a named mutex and event to keep one instance per persona and restore its window on a second launch. `tray.py` dispatches native menu commands through a queue to Tk, and owns a small non-activating wake indicator. Hiding the window leaves workers running; tray Exit performs shutdown.

`startup.py` manages only `FanAssistants.FRIDAY` or `FanAssistants.ALFRED` under the current user's Windows Run key. Settings registers the actual packaged EXE (or source launcher with pythonw), with quoted absolute paths and `--background`. Registration errors are shown in Settings; a failed settings-file save restores the previous registry value. Existing registrations follow a moved launcher on its next normal launch, while externally removed entries stay off. Windows Startup Apps approval is never overridden. Background launch withdraws the window before building the UI and does not signal a duplicate instance to show itself.

`wake.py` detects the assistant name locally using Vosk and preserves audio pre-roll so an inline command is not clipped. Command transcription uses Groq Whisper with Google fallback. Device errors retry instead of silently disabling wake listening. The model is installed separately in Windows app data by `setup_wake.py`.

The brain reconstructs streaming content and tool calls. `streaming.py` queues complete spoken sentences, suppresses code, and caps long speech. Two daemon render workers prepare upcoming audio while the speaker owns playback. Generation tokens invalidate old work on interruption. A late tool-call delta cancels provisional speech; tool arguments never become speech. The final full reply is saved once.

`power.py` provides cancellable ten-second shutdown/restart/sleep/lock actions. These require a directly parsed user command, not a model tool call. Shutdown uses `/t 0` after the local countdown and omits `/f`, allowing unsaved applications to block it. Sleep uses `SetSuspendState` with the shutdown privilege restored afterward.
