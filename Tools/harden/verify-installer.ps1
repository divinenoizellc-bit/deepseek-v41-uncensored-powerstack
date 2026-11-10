#requires -Version 5.1
<#
.SYNOPSIS
    Verify a downloaded installer before you run it: Authenticode signature,
    publisher subject, certificate chain, timestamp, and SHA256.

.DESCRIPTION
    Refuses on mismatch. Never executes the installer. Read-only.

    This exists because the single highest-value habit on a machine that
    downloads a lot of software is: verify, then install. A logo on a landing
    page proves nothing; an affiliate blog's "official download" link is not a
    source. This script checks the two things that are actually hard to fake:

      1. Authenticode - who signed the binary, is the chain trusted, was it
         timestamped (so the signature survives certificate expiry), and is the
         leaf certificate still valid?
      2. SHA256 - that the bytes are the bytes the vendor published.

    A valid Authenticode signature alone is NOT proof of authenticity: an
    attacker with a code-signing certificate (stolen, or bought as a shell
    company) produces a "Valid" signature on malware. That is why the publisher
    subject must ALSO match, and why the SHA256 must come from the vendor's own
    checksum page or release notes - not from the download page's word for it.

.PARAMETER Path
    Path to the downloaded installer. Mandatory unless -ShowTrustedSources or
    -WhatIf is used.

.PARAMETER ExpectedPublisher
    Expected publisher. Matched case-insensitively as a substring of the
    signer's certificate Subject (and of the leaf CN when present).
    Examples: 'Proton AG', 'Mullvad VPN AB', 'IVPN Limited', 'ESET, spol. s r.o.'

.PARAMETER ExpectedSha256
    64 hex characters. Case and surrounding whitespace are ignored.

.PARAMETER ExpectedThumbprint
    Optional signer certificate SHA1 thumbprint, for pinning a specific cert.

.PARAMETER Manifest
    Optional JSON file mapping file names to expectations. Shape:
      { "ProtonVPN_v5.1.9_x64.exe": { "Publisher": "Proton AG", "Sha256": "<hex>" } }

.PARAMETER RequireTimestamp
    Default on. Requires a countersignature so the signature stays valid after
    the signing certificate expires.

.PARAMETER AllowUnsigned
    Explicitly accept an unsigned file. Off by default; most legitimate Windows
    installers are signed.

.PARAMETER ShowTrustedSources
    Print the official download / checksum reference table and exit.

.PARAMETER WhatIf
    Preview the verification plan and the source table without reading the file.
    (This is a read-only tool, so the switch means "do not touch the disk".)

.EXAMPLE
    .\verify-installer.ps1 -Path .\ProtonVPN_v5.1.9_x64.exe -ExpectedPublisher 'Proton AG' -ExpectedSha256 3f2a...

.EXAMPLE
    .\verify-installer.ps1 -ShowTrustedSources

.EXAMPLE
    .\verify-installer.ps1 -Manifest .\manifests\installers.json -Path .\MullvadVPN-2026.4.exe

.NOTES
    Exit codes: 0 pass | 1 verification failed | 2 file missing |
                3 unsigned | 4 invalid signature | 5 bad arguments
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Path,

    [string]$ExpectedPublisher,

    [string]$ExpectedSha256,

    [string]$ExpectedThumbprint,

    [string]$Manifest,

    [switch]$RequireTimestamp = $true,

    [switch]$AllowUnsigned,

    [switch]$ShowTrustedSources,

    [switch]$WhatIf
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$script:DotSourced = ($MyInvocation.InvocationName -eq '.')

# --------------------------------------------------------------------------
# Official-source reference table
# --------------------------------------------------------------------------
# NOTE: these are the vendors' own portals. They are starting points, not
# proof. Navigate to them yourself, then obtain the checksum from the same
# vendor's own checksum/release page and paste it into -ExpectedSha256.
$TrustedSources = @(
    [pscustomobject]@{ Product = 'Mullvad VPN'; Role = 'VPN (primary candidate)'; Publisher = 'Mullvad VPN AB'; Download = 'https://mullvad.net/en/download'; Checksums = 'https://mullvad.net/en/download (per-platform checksums); releases are GPG-signed - key at https://mullvad.net/en/help/verifying-signatures'; Notes = 'Sweden. Open source clients. No affiliate programme.' }
    [pscustomobject]@{ Product = 'Proton VPN'; Role = 'VPN (already installed)'; Publisher = 'Proton AG'; Download = 'https://protonvpn.com/download'; Checksums = 'https://protonvpn.com/support (per-release notes); apps are open source at https://github.com/ProtonVPN'; Notes = 'Switzerland. 5x audited no-logs. Installed here as v5.1.9.' }
    [pscustomobject]@{ Product = 'IVPN'; Role = 'VPN (privacy-max option)'; Publisher = 'IVPN Limited'; Download = 'https://www.ivpn.net/apps-windows/'; Checksums = 'https://www.ivpn.net/en/blog/ release notes carry SHA256; client source at https://github.com/ivpn'; Notes = 'Gibraltar. No affiliates. $60/yr Standard.' }
    [pscustomobject]@{ Product = 'Microsoft Defender'; Role = 'AV (primary)'; Publisher = 'Microsoft Corporation'; Download = 'in-box (Windows Update / Defender platform update)'; Checksums = 'n/a - delivered by Windows Update, verify via Get-MpComputerStatus versions'; Notes = 'No third-party installer needed. Scored 17.7/18 in AV-TEST 2026.' }
    [pscustomobject]@{ Product = 'Bitdefender'; Role = 'AV (paid upgrade candidate)'; Publisher = 'Bitdefender S.R.L.'; Download = 'https://www.bitdefender.com/solutions/'; Checksums = 'https://www.bitdefender.com/site/view/file-hash.html (verify per release)'; Notes = 'Romania. 18/18 in AV-TEST 2026 endurance test.' }
    [pscustomobject]@{ Product = 'ESET'; Role = 'AV (paid upgrade candidate)'; Publisher = 'ESET, spol. s r.o.'; Download = 'https://www.eset.com/us/download/'; Checksums = 'https://support.eset.com/ release notes; installer is Authenticode-signed'; Notes = 'Slovakia. 17.8/18 in AV-TEST 2026.' }
    [pscustomobject]@{ Product = 'Malwarebytes'; Role = 'On-demand second opinion'; Publisher = 'Malwarebytes Inc.'; Download = 'https://www.malwarebytes.com/mwb-download'; Checksums = 'https://support.malwarebytes.com/ release notes'; Notes = 'Free tier is scan-only (no real-time) - use it as a second opinion, not as the primary.' }
    [pscustomobject]@{ Product = 'VirusTotal'; Role = 'Hash lookup / second opinion'; Publisher = 'n/a (Google)'; Download = 'https://www.virustotal.com/gui/'; Checksums = 'n/a'; Notes = 'Look up by SHA256 - no need to upload the file. API key optional.' }
    [pscustomobject]@{ Product = 'Tailscale'; Role = 'Mesh VPN (already installed)'; Publisher = 'Tailscale Inc.'; Download = 'https://tailscale.com/download/windows'; Checksums = 'https://pkgs.tailscale.com/stable/ (signed release metadata)'; Notes = 'WireGuard-based mesh. Already present v1.102.3.' }
)

function Write-Table {
    param([object[]]$Rows, [string[]]$Columns)
    if (-not $Rows -or $Rows.Count -eq 0) { return }
    $Rows | Format-Table -Property $Columns -AutoSize -Wrap | Out-String -Width 4096 | Write-Host
}

function Show-Sources {
    Write-Host ''
    Write-Host '============================================================' -ForegroundColor DarkCyan
    Write-Host ' Official download / checksum pages (primary picks)' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor DarkCyan
    Write-Host ' Treat every download page found via search or an affiliate' -ForegroundColor DarkYellow
    Write-Host ' "best VPN 2026" list as untrusted. Type the vendor domain.' -ForegroundColor DarkYellow
    Write-Host ''
    foreach ($s in $TrustedSources) {
        Write-Host ("  {0}" -f $s.Product) -ForegroundColor White
        Write-Host ("    role        : {0}" -f $s.Role)
        Write-Host ("    signer      : {0}" -f $s.Publisher)
        Write-Host ("    download    : {0}" -f $s.Download)
        Write-Host ("    checksums   : {0}" -f $s.Checksums)
        Write-Host ("    note        : {0}" -f $s.Notes)
        Write-Host ''
    }
    Write-Host ' Gotcha: a "Valid" Authenticode status is NOT proof of authenticity.' -ForegroundColor Yellow
    Write-Host ' Stolen or shell-company code-signing certs produce Valid signatures on' -ForegroundColor Yellow
    Write-Host ' malware. Always pair the signature check with a vendor-published SHA256' -ForegroundColor Yellow
    Write-Host ' AND a publisher check.' -ForegroundColor Yellow
    Write-Host ''
}

if ($ShowTrustedSources) {
    Show-Sources
    if (-not $script:DotSourced) { exit 0 } else { return }
}

if ($WhatIf) {
    Write-Host ''
    Write-Host 'VERIFY-INSTALLER - PREVIEW (nothing will be read or hashed)' -ForegroundColor Yellow
    Write-Host ''
    Write-Host ' Plan:'
    Write-Host '   1. Resolve the file and confirm it exists (refuse if not).'
    Write-Host '   2. Compute SHA256 with Get-FileHash.'
    Write-Host '   3. If -ExpectedSha256 (or a manifest entry) is given, compare exactly.'
    Write-Host '   4. Read Authenticode via Get-AuthenticodeSignature.'
    Write-Host '   5. Require Status = Valid (chain trusted), unless -AllowUnsigned.'
    Write-Host '   6. Require the signer Subject to contain -ExpectedPublisher.'
    Write-Host '   7. Require a timestamp countersignature; require the leaf cert to be in date.'
    Write-Host '   8. Print a PASS/FAIL table and exit non-zero on any failure.'
    Write-Host '   9. Never run, unpack, or modify the file.'
    Write-Host ''
    if ($Path) { Write-Host (" Target would be: {0}" -f $Path) }
    Show-Sources
    if (-not $script:DotSourced) { exit 0 } else { return }
}

# --------------------------------------------------------------------------
# Argument resolution
# --------------------------------------------------------------------------
$failures = New-Object System.Collections.Generic.List[string]
$checks = New-Object System.Collections.Generic.List[object]

function Add-Check {
    param([string]$Name, [string]$Expected, [string]$Actual, [bool]$Pass, [switch]$Fatal)
    $checks.Add([pscustomobject]@{
            Check    = $Name
            Expected = $Expected
            Actual   = $Actual
            Result   = $(if ($Pass) { 'PASS' } else { 'FAIL' })
            Fatal    = [bool]$Fatal
        })
    if (-not $Pass) { $failures.Add($Name) }
}

if (-not $Path) {
    Write-Host 'ERROR: -Path is required (or use -ShowTrustedSources / -WhatIf).' -ForegroundColor Red
    if (-not $script:DotSourced) { exit 5 } else { return }
}

# Manifest lookup can fill in Publisher / Sha256 by file name.
if ($Manifest) {
    if (-not (Test-Path -LiteralPath $Manifest)) {
        Write-Host ("ERROR: manifest not found: {0}" -f $Manifest) -ForegroundColor Red
        if (-not $script:DotSourced) { exit 5 } else { return }
    }
    try {
        $mf = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json
        $leaf = Split-Path -Leaf $Path
        $entry = $null
        foreach ($prop in $mf.PSObject.Properties) {
            if ($prop.Name -ieq $leaf) { $entry = $prop.Value; break }
        }
        if ($entry) {
            if (-not $ExpectedPublisher -and $entry.Publisher) { $ExpectedPublisher = [string]$entry.Publisher }
            if (-not $ExpectedSha256 -and $entry.Sha256) { $ExpectedSha256 = [string]$entry.Sha256 }
            Write-Host (" Manifest entry found for '{0}'." -f $leaf) -ForegroundColor DarkGray
        }
        else {
            Write-Host (" No manifest entry for '{0}'; using command-line expectations only." -f $leaf) -ForegroundColor DarkYellow
        }
    }
    catch {
        Write-Host ("ERROR: manifest is not valid JSON: {0}" -f $_.Exception.Message) -ForegroundColor Red
        if (-not $script:DotSourced) { exit 5 } else { return }
    }
}

$full = $null
try { $full = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).ProviderPath }
catch { $full = $null }

if (-not $full -or -not (Test-Path -LiteralPath $full -PathType Leaf)) {
    Write-Host ("ERROR: file not found: {0}" -f $Path) -ForegroundColor Red
    if (-not $script:DotSourced) { exit 2 } else { return }
}

Write-Host ''
Write-Host '============================================================' -ForegroundColor DarkCyan
Write-Host ' Installer verification' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor DarkCyan
Write-Host (" File     : {0}" -f $full)

$fi = Get-Item -LiteralPath $full
Write-Host (" Size     : {0:N0} bytes ({1:N2} MiB)" -f $fi.Length, ($fi.Length / 1MB))
Write-Host (" Modified : {0:o}" -f $fi.LastWriteTimeUtc)
Write-Host (" Zone     : {0}" -f $(try {
            $adi = Get-Content -LiteralPath ($full + ':Zone.Identifier') -ErrorAction Stop
            ($adi | Where-Object { $_ -match '^ZoneId=' }) -join ' '
        }
        catch { 'no Mark-of-the-Web stream (locally built or stream stripped)' }))
Write-Host ''

# --------------------------------------------------------------------------
# 1. SHA256
# --------------------------------------------------------------------------
Write-Host ' Hashing (SHA256)...' -ForegroundColor DarkGray
$actualHash = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToUpperInvariant()
Write-Host (" Actual   : {0}" -f $actualHash)

$expHash = $null
if ($ExpectedSha256) { $expHash = ($ExpectedSha256 -replace '\s', '').ToUpperInvariant() }

if ($expHash) {
    if ($expHash -match '^[0-9A-F]{64}$') {
        Add-Check -Name 'SHA256' -Expected $expHash -Actual $actualHash -Pass ($expHash -eq $actualHash) -Fatal
    }
    else {
        Write-Host 'ERROR: -ExpectedSha256 is not 64 hex characters.' -ForegroundColor Red
        if (-not $script:DotSourced) { exit 5 } else { return }
    }
}
else {
    Add-Check -Name 'SHA256' -Expected '(not supplied)' -Actual $actualHash -Pass $true
    Write-Host ' WARNING: no expected SHA256 supplied. Integrity is UNVERIFIED.' -ForegroundColor Yellow
    Write-Host '          Copy the hash from the vendor checksum page and re-run with' -ForegroundColor Yellow
    Write-Host '          -ExpectedSha256. A signature alone does not prove bytes.' -ForegroundColor Yellow
}

# --------------------------------------------------------------------------
# 2. Authenticode
# --------------------------------------------------------------------------
Write-Host ''
Write-Host ' Checking Authenticode...' -ForegroundColor DarkGray
$sig = Get-AuthenticodeSignature -LiteralPath $full

Add-Check -Name 'SignatureStatus' -Expected 'Valid' -Actual "$($sig.Status)" -Pass ($sig.Status -eq 'Valid') -Fatal

$subject = ''
$thumb = ''
$notAfter = ''
$isExpired = $null
if ($sig.SignerCertificate) {
    $subject = [string]$sig.SignerCertificate.Subject
    $thumb = [string]$sig.SignerCertificate.Thumbprint
    $notAfter = ([datetime]$sig.SignerCertificate.NotAfter).ToString('yyyy-MM-dd')
    $isExpired = ([datetime]$sig.SignerCertificate.NotAfter) -lt (Get-Date)
    Write-Host (" Signer   : {0}" -f $subject)
    Write-Host (" Thumb    : {0}" -f $thumb)
    Write-Host (" Cert     : expires {0}" -f $notAfter)
}
else {
    Write-Host ' Signer   : (none)' -ForegroundColor Yellow
}

# Unsigned handling
if (-not $sig.SignerCertificate) {
    if ($AllowUnsigned) {
        Write-Host ' NOTE: unsigned file accepted because -AllowUnsigned was passed.' -ForegroundColor Yellow
    }
    else {
        Add-Check -Name 'Signed' -Expected 'signed' -Actual 'unsigned' -Pass $false -Fatal
    }
}

# Publisher match
if ($ExpectedPublisher) {
    $pubOk = $false
    if ($sig.SignerCertificate) {
        $needle = $ExpectedPublisher.Trim()
        $pubOk = ($subject -like ('*' + $needle + '*'))
        if (-not $pubOk) {
            # Also try the leaf CN, which is sometimes friendlier than the full DN.
            $cn = [regex]::Match($subject, 'CN=([^,]+)')
            if ($cn.Success -and $cn.Groups[1].Value -like ('*' + $needle + '*')) { $pubOk = $true }
        }
    }
    Add-Check -Name 'Publisher' -Expected $ExpectedPublisher -Actual $(if ($subject) { $subject } else { '(unsigned)' }) -Pass $pubOk -Fatal
}
else {
    Add-Check -Name 'Publisher' -Expected '(not supplied)' -Actual $(if ($subject) { $subject } else { '(unsigned)' }) -Pass $true
    Write-Host ' WARNING: no expected publisher supplied. You cannot tell who signed this.' -ForegroundColor Yellow
}

# Thumbprint pin
if ($ExpectedThumbprint) {
    $tp = ($ExpectedThumbprint -replace '\s', '').ToUpperInvariant()
    Add-Check -Name 'SignerThumbprint' -Expected $tp -Actual $thumb -Pass ($tp -eq $thumb.ToUpperInvariant()) -Fatal
}

# Chain / validity
if ($sig.SignerCertificate) {
    Add-Check -Name 'CertNotExpired' -Expected 'in date' -Actual $notAfter -Pass (-not $isExpired) -Fatal
}

# Timestamp countersignature
$tsa = ''
if ($sig.TimeStamperCertificate) { $tsa = [string]$sig.TimeStamperCertificate.Subject }
if ($RequireTimestamp) {
    Add-Check -Name 'Timestamped' -Expected 'countersigned' -Actual $(if ($tsa) { $tsa } else { '(none)' }) -Pass ([bool]$tsa)
}
elseif ($tsa) {
    Write-Host (" Timestamp: {0}" -f $tsa) -ForegroundColor DarkGray
}

# --------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------
Write-Host ''
Write-Host '------------------------------------------------------------' -ForegroundColor DarkGray
$checks | Format-Table -Property Check, Result, Expected, Actual -AutoSize -Wrap | Out-String -Width 4096 | Write-Host
Write-Host '------------------------------------------------------------' -ForegroundColor DarkGray

$hardFail = @($checks | Where-Object { $_.Result -eq 'FAIL' -and $_.Fatal })
$softFail = @($checks | Where-Object { $_.Result -eq 'FAIL' -and -not $_.Fatal })

if ($hardFail.Count -eq 0 -and $softFail.Count -eq 0) {
    Write-Host ''
    if (-not $expHash -or -not $ExpectedPublisher) {
        Write-Host ' RESULT: PARTIAL - signature checks passed, integrity NOT proven.' -ForegroundColor Yellow
        Write-Host ' You did not supply every expectation, so this file is signed but' -ForegroundColor Yellow
        Write-Host ' not authenticated. Re-run with -ExpectedPublisher and -ExpectedSha256.' -ForegroundColor Yellow
    }
    else {
        Write-Host ' RESULT: PASS - signature, publisher and hash all match.' -ForegroundColor Green
        Write-Host ' You may run the installer. This script will not run it for you.' -ForegroundColor Green
    }
    Write-Host ''
    if (-not $script:DotSourced) { exit 0 } else { return }
}

Write-Host ''
Write-Host ' RESULT: REFUSED - do not run this file.' -ForegroundColor Red
foreach ($f in $checks | Where-Object { $_.Result -eq 'FAIL' }) {
    Write-Host ("   x {0}: expected '{1}', got '{2}'" -f $f.Check, $f.Expected, $f.Actual) -ForegroundColor Red
}
Write-Host ''

$code = 1
if (($checks | Where-Object { $_.Check -eq 'Signed' -and $_.Result -eq 'FAIL' })) { $code = 3 }
elseif (($checks | Where-Object { $_.Check -eq 'SignatureStatus' -and $_.Result -eq 'FAIL' })) { $code = 4 }

Write-Host ' Next: re-download from the vendor domain in -ShowTrustedSources,' -ForegroundColor Yellow
Write-Host ' re-read the checksum from the vendor page, and verify again.' -ForegroundColor Yellow
Write-Host ''
if (-not $script:DotSourced) { exit $code } else { return }
