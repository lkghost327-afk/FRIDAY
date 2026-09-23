param([string]$Directory = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
# Original publisher: https://github.com/lkghost327-afk
# Obtain this verifier from the original repository, not from an unknown mirror.
$expectedKey = '5111ff26aa40aa8d927d0e8a9f191c82bb007d360eaacca9a4366cd3d6da3e0a'
$root = (Resolve-Path -LiteralPath $Directory).Path
$keyPath = Join-Path $root 'PUBLISHER-KEY.xml'
if ((Get-FileHash -LiteralPath $keyPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedKey) {
    throw 'Publisher key does not match lkghost327-afk.'
}
$rsa = [System.Security.Cryptography.RSA]::Create()
try {
    $rsa.FromXmlString([System.IO.File]::ReadAllText($keyPath))
    $bytes = [System.IO.File]::ReadAllBytes((Join-Path $root 'RELEASE-MANIFEST.json'))
    $signature = [Convert]::FromBase64String([System.IO.File]::ReadAllText((Join-Path $root 'RELEASE-MANIFEST.sig')))
    if (-not $rsa.VerifyData($bytes, $signature, [System.Security.Cryptography.HashAlgorithmName]::SHA256, [System.Security.Cryptography.RSASignaturePadding]::Pkcs1)) {
        throw 'Release manifest signature is invalid. Do not use these downloads.'
    }
    $manifest = [System.Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or $manifest.publisher -ne 'lkghost327-afk' -or
        $manifest.key_sha256 -ne $expectedKey -or
        $manifest.repository -notin @('https://github.com/lkghost327-afk/FRIDAY','https://github.com/lkghost327-afk/ALFRED') -or
        $manifest.source_commit -notmatch '^[a-f0-9]{40}$') {
        throw 'Invalid publisher or source identity in the manifest.'
    }
    $seen = @{}
    if ($manifest.files.Count -lt 2 -or $manifest.files.Count -gt 12) { throw 'Invalid release asset list.' }
    foreach ($file in $manifest.files) {
        if ($file.name -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]+$' -or $file.name -match '\.\.' -or
            $seen.ContainsKey($file.name) -or $file.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Invalid release asset path or hash.' }
        $seen[$file.name] = $true
        $path = Join-Path $root $file.name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing release asset: $($file.name)" }
        if ((Get-Item -LiteralPath $path).Length -ne $file.size -or
            (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.sha256) {
            throw "Release asset was changed: $($file.name)"
        }
    }
    Write-Output "VERIFIED: $($manifest.publisher) / $($manifest.repository) / v$($manifest.version)"
    Write-Output "Source commit: $($manifest.source_commit)"
    Write-Output 'Signature and all listed file checksums match the pinned publisher key.'
} finally { $rsa.Dispose() }
