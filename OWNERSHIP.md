# Publisher attribution and release verification

**Original project publisher:** [lkghost327-afk](https://github.com/lkghost327-afk)

Original repositories:
- https://github.com/lkghost327-afk/FRIDAY
- https://github.com/lkghost327-afk/ALFRED

The original project code attributes this publisher in `assistant_core/ownership.py`,
Settings and diagnostic output. This attribution does not cover third-party code,
speech models, Iron Man/Batman characters or their trademarks, and does not change
the licenses of those components.

## Verify a downloaded release

The release includes a manifest naming its repository, source commit and asset
SHA-256 hashes, signed with the publisher's RSA-3072 key using SHA-256. The public
key is pinned in the app and verification script with this fingerprint:

```text
5111ff26aa40aa8d927d0e8a9f191c82bb007d360eaacca9a4366cd3d6da3e0a
```

Download all release assets into one folder. Get `Verify-Release.ps1` from the
original repository or release, then run:

```powershell
powershell -NoProfile -File .\Verify-Release.ps1 -Directory .
```

The verifier checks the pinned public key, manifest signature, repository identity
and every listed file's size/hash. A changed manifest, key or asset fails validation.
If Windows blocks a downloaded script, inspect the script and follow your own
Windows execution policy; changing machine-wide policy is not required by the app.

The private signing key is never included in source, applications or releases.
On the publisher's development PC it is encrypted for the current Windows account
under `%LOCALAPPDATA%\FanAssistants\publisher\`. Keep that account and key backed up
securely; replacing the key requires a documented public-key rotation.

A valid signature links a release to the key published in these repositories and
detects tampering. It is not an independent legal ownership determination or a
Windows Authenticode certificate. Windows may still show an unknown-publisher
warning. Attribution can be copied, so always verify against the original GitHub
repository and pinned fingerprint.
