# Windows beta.4 verification

Verified on the development Windows 11 x64 system on 2026-10-28.

- FRIDAY: 215 offline tests passed. ALFRED: 215 offline tests passed.
- Shared core modules match between both repositories.
- Existing Vosk model: 14 synthetic Windows speech cases passed, including positive names, cross-persona rejection and unrelated phrases. No microphone recording was used for this check.
- Wake regressions cover both decoder completion orders, stale candidates, split-name pronunciations, sensitivity, reset and detector retry. The failed-detector state leaves Talk usable.
- Native Windows fixtures: accessible text read, password excluded, Hindi/English text inserted literally, both shortcut registrations cleaned up.
- Packaged EXEs: version, modules, model presence and credential-pattern checks passed.
- Both EXEs passed offline dependency diagnostics and fresh-profile UI startup/exit with no personal API key.
- Both passed background UI startup/exit and launch from an unrelated working directory containing spaces and Hindi characters. These smoke tests do not open the microphone or test live wake while hidden.
- Compact wake-switch layout was visually inspected on Windows. The unit suite checks synchronization with the other wake controls.
- All publishable repository files were checked for credential-shaped material and reference-product branding.

## Limits

Synthetic speech is not evidence of human microphone accuracy. Live human wake accuracy and cloud recognition/reply latency remain unverified for this build. Cloud conversation and transcription require a working personal API key. No new speech model was downloaded, no microphone recording was saved, and no personal profile/key is included.

Installers were compiled from the tested portable binaries. Clean-VM installation/uninstallation and every third-party app combination have not been verified. Windows accessibility support varies by app. This build does not implement universal visual clicking, meetings, background agents or full feature parity with another assistant; see the repository coverage document.

EXEs are not Windows Authenticode-signed. The publisher-signed release manifest and pinned public key verify release integrity and publisher provenance; they do not certify application behavior.
