# FRIDAY and ALFRED v5.1 execution plan

Status: v5.1.0-beta.1 implementation complete; release validation in progress. See [measured results and outstanding acceptance gates](VALIDATION-v5.1.md).
Current stable release: v5.0.0.
Applies to both independent repositories, with shared functionality kept synchronized and separate personas, settings and data preserved.

## 1. Establish a performance baseline

- Measure wake detection, transcription, first spoken response, interruption delay, CPU and memory.
- Create repeatable command sets for quiet rooms, background noise and different microphones.
- Record missed wake words, accidental activations, wrong interpretations and incorrect actions.

Completion: a baseline report identifying the largest delays and failure rates.

## 2. Improve conversation speed and listening

- Evaluate streaming cloud transcription alongside existing local recognition.
- Tune end-of-speech detection and pauses.
- Improve spoken interruptions, echo handling and cancellation.
- Benchmark voice options for naturalness, latency and availability before choosing a provider.

Initial targets: stop playback within 500 ms of a recognized interruption; aim for first spoken response within three seconds on the agreed test setup. Establish achievable targets from the baseline and report network-dependent results separately.

## 3. Make app control dependable

- Add dedicated support for frequently used apps, starting with Spotify, browsers, File Explorer and Notepad.
- Improve app-name matching and selection when multiple windows are open.
- Isolate potentially blocking UI Automation in a worker with a firm timeout.
- Verify outcomes and explain failures clearly.
- Ensure cancelled or timed-out commands cannot execute later.

Completion: a documented supported-command list, repeatable success checks and no wrong-app actions in the test set.

## 4. Strengthen background operation

- Handle sleep/resume, unplugged microphones, Bluetooth changes and network outages.
- Verify startup after an actual Windows sign-in.
- Measure memory growth, CPU and recovery during extended background operation.
- Keep the corner indicator consistent with listening, processing and speaking.

Completion: an eight-hour background test plus device reconnection, startup and sleep/resume checks. Schedule disruptive device tests when the user is ready.

## 5. Improve setup and release verification

- Add guided microphone selection, visible input levels, calibration and voice playback tests.
- Clearly show which audio processing is local and which uses an online service.
- Integrate the existing pinned publisher-key and signed-manifest verification into the updater.
- Add update recovery and preserve personal settings during upgrades.
- Evaluate Windows Authenticode signing options. Identity registration, subscriptions and costs require a separate decision; do not purchase or enroll automatically.

Completion: a new user can install, configure, verify and update either assistant without developer tools.

## 6. Validate and release

- Run both regression suites.
- Test fresh installations and upgrades from v5 on clean Windows environments.
- Test real microphones and supported applications.
- Rebuild installers and portable EXEs, compare packaged code with source, and sign final release manifests.
- Publish a beta for hands-on testing before promoting it to stable.
- Document measured improvements, remaining limitations and supported commands.

## Execution order and release gates

Start with measurement and voice responsiveness, then app-control reliability.
Keep v5 available while v5.1 is developed.
Do not claim hardware reliability from mocked tests alone.
Do not publish a stable build until its package, upgrade, signature and real-device checks pass.
Preserve the existing publisher identity and protected signing key; never put private signing material in either repository.
