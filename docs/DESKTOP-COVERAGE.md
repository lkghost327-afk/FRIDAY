# Desktop interaction coverage — 5.1.0-beta.4

This is a Windows implementation with its own personas. The following is an honest coverage map, not a claim of universal app control or full feature parity.

| Experience | Current implementation | Remaining work |
|---|---|---|
| Talk shortcut | Opt-in Ctrl+Alt+F / Ctrl+Alt+A; hold, toggle or pause; Escape cancellation from other apps | Remappable shortcuts and native fn-key handling |
| Voice capture | Raw onset gate, 400 ms preroll, frozen speech threshold, 0.95 s default pause, bounded gain, live English preview | Real user accuracy/latency validation with a valid cloud key; quality varies by microphone |
| Final transcript | Partial text is display-only; final provider text dispatches commands; recording limits open a local review | Confidence-based correction UI and provider-failure draft recovery |
| Voice services | Groq accuracy/speed selection, optional Deepgram streaming, Google and existing local English options | Apple on-device speech is not available on Windows; no new models downloaded |
| Interface | Compact conversation window, expanded dashboard, live caption/meter, corner status card, request recall | Full command-palette visual parity, rich task cards, reduced-motion preference |
| Conversation reuse | Up recalls last typed request; double-click a request to edit or an answer to copy | Rich Markdown cards and per-response actions |
| Dictation | Bound Windows accessibility field, literal Unicode, selection when available, no submission, failure preview | Dictation archive/statistics, custom dictionary, cleanup mode, unsupported editor adapters |
| App commands | Installed-app discovery, window/media controls, accessible app context and named controls | App-by-app compatibility testing; arbitrary visual clicking is not implemented |
| Screen understanding | Explicit screen questions send one in-memory image; no background screen sharing | Point/crop input, drawn annotations, target-window live preview |
| Saved phrases | Explicit named routines, maximum eight validated steps, cancellation and verification | Learning successful model-generated routines automatically |
| Memory | User-requested facts and conversation history | Rich memory editing/search UI |
| Background operation | Tray, opt-in wake and Windows startup, device recovery | Independent background job cards, steering, task resumption |
| Meeting assistance | Not implemented | Explicit recording controls, loopback capture, archive, recap and consent UX |
| Watchers/schedules | Existing timers/reminders | Condition-based app watchers and scheduled agent jobs |
| AI connection | Per-user Groq key, first-run verification, Settings key test | Subscription-client adapters and additional model providers |
| Distribution | Separate Windows EXEs, owner metadata, no bundled user key | Final live voice acceptance; Windows EXEs are not Authenticode-signed |

## Release acceptance boundary

Synthetic PCM and mocked provider tests cannot establish human recognition accuracy. Native fixture tests cover only the controls explicitly exercised. The live microphone captured audio, but both Groq model requests were rejected by the configured key. That service must authenticate before an end-to-end cloud speech comparison can pass.

No API keys, personal profile data or recorded microphone audio belong in source or release packages.
