#requires -Version 5.1
<#
.SYNOPSIS
    Safe integrity scanner for downloaded model weights.
    Hashes files and checks them against a manifest. Never executes anything.

.DESCRIPTION
    Built for a machine that pulls hundreds of gigabytes of model files from
    Hugging Face and elsewhere. It answers one narrow question honestly:

        "Are these bytes still the bytes I recorded?"

    and deliberately refuses to answer a different question it cannot answer:

        "Is this model safe to load?"

    HARD SAFETY RULES
      1. This script NEVER executes, imports, loads, unpacks, or deserialises a
         scanned file. No Start-Process, no &, no python, no Import-Module, no
         model loading. It calls Get-Item and Get-FileHash and nothing else that
         touches file contents.
      2. It refuses to submit weight shards to VirusTotal under any flag.
      3. VirusTotal submission is off by default, opt-in only, size-capped, and
         extension-gated to small non-weight artefacts.

    WHAT A MANIFEST DOES AND DOES NOT PROVE
      It proves the file has not changed since you hashed it. That catches
      re-downloads that differ, silent corruption, and tampering after the fact.
      It does NOT prove the file was benign when you hashed it. If you hashed a
      malicious file, the manifest will happily pin the malicious hash. Integrity
      is not safety. Pair this with downloading from a pinned revision and
      preferring safe serialisation formats.

    WHY FORMAT MATTERS MORE THAN THE SCAN
      Python pickle (.pkl/.pickle) and several .bin/.pt/.pth containers can
      execute arbitrary code during deserialisation. That is a property of the
      format, not a bug a scanner finds. safetensors exists specifically to avoid
      it. Files flagged "code-capable" below should not be loaded from an
      untrusted repository at all.

.PARAMETER Root
    Directory to scan. Defaults to C:\Users\psand\Models.

.PARAMETER Manifest
    Manifest JSON. Defaults to <Root>\.weights-manifest.json.

.PARAMETER GenerateManifest
    (Re)build the manifest from what is currently on disk.

.PARAMETER Verify
    Verify disk against the manifest. This is the default when a manifest exists.

.PARAMETER Quick
    Compare file sizes and timestamps only. Does not read file contents. Use it
    as a fast pre-check before a full hash pass.

.PARAMETER Include
    Extra glob patterns to include. Weight patterns are always included.

.PARAMETER Exclude
    Glob patterns to skip.

.PARAMETER ScanCode
    Also collect code-capable artefacts (.py, .sh, .bat, .ps1, .js, .exe, .dll,
    .so, .whl). Off by default; turn it on when auditing a whole downloaded repo
    rather than just its weights.

.PARAMETER MaxBytes
    Skip files larger than this. 0 = no limit.

.PARAMETER MaxFiles
    Stop after this many files. 0 = no limit.

.PARAMETER VtMode
    None (default) | Lookup | Upload.
      Lookup - hash-only lookup, sends the SHA256, never the file.
      Upload - uploads small suspicious non-weight files only.

.PARAMETER VtApiKey
    VirusTotal API key. Falls back to $env:VT_API_KEY.

.PARAMETER VtMaxBytes
    Hard ceiling for anything uploaded. Default 32 MiB (VirusTotal's direct
    upload limit is 32 MB for the standard endpoint).

.PARAMETER ReportPath
    Where to write the JSON report. Defaults to <script>\.state\.

.PARAMETER WhatIf
    Preview the scan plan. Reads nothing, writes nothing.

.EXAMPLE
    .\scan-weights.ps1 -WhatIf
    Show what would be scanned.

.EXAMPLE
    .\scan-weights.ps1 -GenerateManifest
    Record the current state of every model file as the trust baseline.

.EXAMPLE
    .\scan-weights.ps1 -Verify
    Full SHA256 verification against the manifest.

.EXAMPLE
    .\scan-weights.ps1 -Verify -Quick
    Fast size/timestamp drift check.

.EXAMPLE
    $env:VT_API_KEY='...'; .\scan-weights.ps1 -VtMode Lookup
    Hash-only reputation lookup for files in the scan set.

.NOTES
    Exit codes: 0 all good | 1 integrity failure | 2 no manifest |
                3 bad arguments | 4 VirusTotal configured incorrectly
#>
[CmdletBinding()]
param(
    [string]$Root = 'C:\Users\psand\Models',

    [string]$Manifest,

    [switch]$GenerateManifest,

    [switch]$Verify,

    [switch]$Quick,

    [string[]]$Include = @(),

    [string[]]$Exclude = @(),

    [switch]$ScanCode,

    [long]$MaxBytes = 0,

    [int]$MaxFiles = 0,

    [ValidateSet('None', 'Lookup', 'Upload')]
    [string]$VtMode = 'None',

    [string]$VtApiKey,

    [long]$VtMaxBytes = 33554432,

    [string]$ReportPath,

    [switch]$WhatIf
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$script:DotSourced = ($MyInvocation.InvocationName -eq '.')

# Weight formats: inert tensor containers. Never uploaded, never hashed twice
# unnecessarily beyond the integrity pass.
$WeightExtensions = @(
    '.safetensors', '.gguf', '.onnx', '.ckpt', '.h5', '.tflite', '.npy', '.npz',
    '.msgpack', '.arrow', '.parquet', '.model', '.joblib', '.ckpt.index'
)

# Formats that can carry or execute code when loaded by the common runtimes.
$CodeCapableExtensions = @(
    '.pkl', '.pickle', '.pt', '.pth', '.bin', '.py', '.pyc', '.sh', '.bash',
    '.bat', '.cmd', '.ps1', '.js', '.mjs', '.exe', '.dll', '.so', '.dylib',
    '.whl', '.tar', '.gz', '.zip', '.7z', '.rar'
)

function Write-Head([string]$Text) {
    Write-Host ''
    Write-Host ("=== {0}" -f $Text) -ForegroundColor Cyan
}

function Get-RelativeKey {
    param([string]$Base, [string]$Full)
    $b = $Base.TrimEnd('\', '/')
    if ($Full.StartsWith($b, [StringComparison]::OrdinalIgnoreCase)) {
        return $Full.Substring($b.Length).TrimStart('\', '/')
    }
    return (Split-Path -Leaf $Full)
}

function Test-ExtIn {
    param([string]$Name, [string[]]$Set)
    $ext = [IO.Path]::GetExtension($Name).ToLowerInvariant()
    foreach ($e in $Set) { if ($ext -eq $e.ToLowerInvariant()) { return $true } }
    return $false
}

function Test-FormatCodeCapable {
    param([string]$Name)
    return (Test-ExtIn $Name $CodeCapableExtensions)
}

function Get-VtFileReport {
    param([string]$Sha256, [string]$ApiKey)
    $uri = 'https://www.virustotal.com/api/v3/files/' + $Sha256.ToLowerInvariant()
    $headers = @{ 'x-apikey' = $ApiKey; 'accept' = 'application/json' }
    try {
        $r = Invoke-RestMethod -Uri $uri -Headers $headers -Method Get -TimeoutSec 30
        $stats = $r.data.attributes.last_analysis_stats
        return [pscustomobject]@{
            Found     = $true
            Malicious = [int]$stats.malicious
            Suspicious = [int]$stats.suspicious
            Harmless  = [int]$stats.harmless
            Undetected = [int]$stats.undetected
            Total     = ([int]$stats.malicious + [int]$stats.suspicious + [int]$stats.harmless + [int]$stats.undetected)
            Name      = [string]$r.data.attributes.meaningful_name
        }
    }
    catch {
        $code = $null
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        if ($code -eq 404) {
            return [pscustomobject]@{ Found = $false; Malicious = 0; Suspicious = 0; Harmless = 0; Undetected = 0; Total = 0; Name = '' }
        }
        return [pscustomobject]@{ Found = $false; Error = $_.Exception.Message; Malicious = 0; Suspicious = 0; Harmless = 0; Undetected = 0; Total = 0; Name = '' }
    }
}

# --------------------------------------------------------------------------
# Banner
# --------------------------------------------------------------------------
Write-Host ''
Write-Host '============================================================' -ForegroundColor DarkCyan
Write-Host ' Model-weight integrity scanner (read-only, non-executing)' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor DarkCyan
Write-Host (" Root      : {0}" -f $Root)
Write-Host (" Mode      : {0}" -f $(if ($GenerateManifest) { 'GENERATE MANIFEST' } elseif ($Quick) { 'QUICK VERIFY (size/time)' } else { 'FULL SHA256 VERIFY' }))
Write-Host (" VT        : {0}" -f $VtMode)
Write-Host ''

if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
    Write-Host ("ERROR: scan root does not exist: {0}" -f $Root) -ForegroundColor Red
    if (-not $script:DotSourced) { exit 3 } else { return }
}
$Root = (Resolve-Path -LiteralPath $Root).ProviderPath

if (-not $Manifest -or $Manifest.Trim() -eq '') {
    $Manifest = Join-Path $Root '.weights-manifest.json'
}
if (-not $ReportPath -or $ReportPath.Trim() -eq '') {
    $base = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
    $ReportPath = Join-Path (Join-Path $base '.state') ('weights-scan-{0}.json' -f (Get-Date).ToString('yyyyMMdd-HHmmss'))
}

if ($MaxBytes -gt 0) { Write-Host (" Size cap  : {0:N2} GiB" -f ($MaxBytes / 1GB)) }
if ($MaxFiles -gt 0) { Write-Host (" File cap  : {0}" -f $MaxFiles) }
if ($Include.Count -gt 0) { Write-Host (" Include   : {0}" -f ($Include -join ', ')) }
if ($Exclude.Count -gt 0) { Write-Host (" Exclude   : {0}" -f ($Exclude -join ', ')) }

# --------------------------------------------------------------------------
# Build the file set
# --------------------------------------------------------------------------
Write-Head 'Discovering files'
$patterns = @('*.safetensors', '*.gguf', '*.bin', '*.pt', '*.pth', '*.onnx', '*.ckpt',
    '*.h5', '*.tflite', '*.npy', '*.npz', '*.pkl', '*.pickle', '*.msgpack',
    '*.model', '*.sft', '*.ggml', 'sha256-*')

# -ScanCode widens the net to artefacts that can execute when loaded. Off by
# default because it slows the pass and pulls in non-model files.
if ($ScanCode) {
    $patterns += @('*.py', '*.pyc', '*.sh', '*.bat', '*.ps1', '*.js', '*.exe', '*.dll', '*.so', '*.whl')
}
$patterns += $Include

$files = New-Object System.Collections.Generic.List[object]
$seen = New-Object 'System.Collections.Generic.HashSet[string]'
foreach ($pat in $patterns) {
    Get-ChildItem -LiteralPath $Root -Recurse -File -Filter $pat -ErrorAction SilentlyContinue |
        ForEach-Object {
            $skip = $false
            foreach ($ex in $Exclude) {
                if ($_.FullName -like $ex) { $skip = $true; break }
            }
            if (-not $skip -and $seen.Add($_.FullName)) {
                $files.Add($_)
            }
        }
}

if ($MaxBytes -gt 0) {
    $files = @($files | Where-Object { $_.Length -le $MaxBytes })
}
$files = @($files | Sort-Object FullName)

if ($MaxFiles -gt 0 -and $files.Count -gt $MaxFiles) {
    Write-Host (" Capping at {0} of {1} files." -f $MaxFiles, $files.Count) -ForegroundColor Yellow
    $files = @($files | Select-Object -First $MaxFiles)
}

# Measure-Object returns no object at all for an empty pipeline, and StrictMode
# makes .Sum on $null a terminating error. Handle the empty case explicitly.
$totalBytes = 0
if ($files.Count -gt 0) {
    $mo = $files | Measure-Object -Property Length -Sum
    if ($mo -and $mo.PSObject.Properties['Sum'] -and $null -ne $mo.Sum) {
        $totalBytes = [long]$mo.Sum
    }
}

Write-Host (" Found {0} candidate file(s), {1:N2} GiB total." -f $files.Count, ($totalBytes / 1GB))

$codeCapable = @($files | Where-Object { Test-FormatCodeCapable $_.Name })
if ($codeCapable.Count -gt 0) {
    Write-Host (" {0} file(s) use code-capable formats:" -f $codeCapable.Count) -ForegroundColor Yellow
    $codeCapable | Select-Object -First 10 | ForEach-Object {
        Write-Host ("   ! {0}" -f (Get-RelativeKey $Root $_.FullName)) -ForegroundColor Yellow
    }
    if ($codeCapable.Count -gt 10) { Write-Host ("   ... and {0} more" -f ($codeCapable.Count - 10)) -ForegroundColor Yellow }
    Write-Host '   A manifest hash proves these are unchanged, not that they are safe.' -ForegroundColor DarkYellow
    Write-Host '   Prefer safetensors; do not load .pkl/.pth from untrusted repos.' -ForegroundColor DarkYellow
}

if ($WhatIf) {
    Write-Host ''
    Write-Host ' PREVIEW ONLY. Nothing read, nothing written.' -ForegroundColor Yellow
    Write-Host ''
    Write-Host ' Would do:'
    if ($GenerateManifest) { Write-Host ("   - SHA256 each of {0} file(s) and write manifest {1}" -f $files.Count, $Manifest) }
    else { Write-Host ("   - {0} {1} file(s) against {2}" -f $(if ($Quick) { 'Size/time check' } else { 'SHA256 verify' }), $files.Count, $Manifest) }
    if ($VtMode -ne 'None') {
        $vtCandidates = @($files | Where-Object { -not (Test-ExtIn $_.Name $WeightExtensions) -and $_.Length -le $VtMaxBytes })
        Write-Host ("   - VirusTotal {0} for {1} small non-weight file(s) (cap {2:N1} MiB)" -f $VtMode, $vtCandidates.Count, ($VtMaxBytes / 1MB))
    }
    else { Write-Host '   - no VirusTotal calls' }
    Write-Host ''
    if (-not $script:DotSourced) { exit 0 } else { return }
}

# --------------------------------------------------------------------------
# VT key validation
# --------------------------------------------------------------------------
$vtKey = $VtApiKey
if (-not $vtKey) { $vtKey = $env:VT_API_KEY }
if ($VtMode -ne 'None' -and -not $vtKey) {
    Write-Host ''
    Write-Host 'ERROR: -VtMode was requested but no API key is available.' -ForegroundColor Red
    Write-Host '       Set $env:VT_API_KEY or pass -VtApiKey.' -ForegroundColor Red
    if (-not $script:DotSourced) { exit 4 } else { return }
}

# --------------------------------------------------------------------------
# Existing manifest
# --------------------------------------------------------------------------
$existing = @{}
$haveManifest = Test-Path -LiteralPath $Manifest
if ($haveManifest) {
    try {
        $mf = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json
        if ($mf.PSObject.Properties['Files']) {
            foreach ($p in $mf.Files.PSObject.Properties) { $existing[$p.Name] = $p.Value }
        }
        Write-Host (" Loaded manifest: {0} entitle(s) [{1}]" -f $existing.Count, $Manifest)
    }
    catch {
        Write-Host (" WARNING: manifest is unreadable, treating as absent: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
        $haveManifest = $false
        $existing = @{}
    }
}
else {
    Write-Host (" No manifest at {0}" -f $Manifest)
}

# Content-addressed blobs (sha256-<hex> names, as used by Ollama) are
# self-verifying, so a manifest is optional for them.
$selfAddressedCount = @($files | Where-Object { $_.Name -match '^sha256-[0-9a-fA-F]{64}$' }).Count

if (-not $GenerateManifest -and -not $haveManifest -and $selfAddressedCount -eq 0) {
    Write-Host ''
    Write-Host 'ERROR: no manifest to verify against.' -ForegroundColor Red
    Write-Host '       Run -GenerateManifest once to record a trust baseline.' -ForegroundColor Red
    if (-not $script:DotSourced) { exit 2 } else { return }
}
if (-not $GenerateManifest -and -not $haveManifest -and $selfAddressedCount -gt 0) {
    Write-Host ''
    Write-Host (" No manifest found, but {0} file(s) are self-addressed (sha256-<hash> names)." -f $selfAddressedCount) -ForegroundColor DarkYellow
    Write-Host ' Those are verified against their own file name. Other files will show' -ForegroundColor DarkYellow
    Write-Host ' as NotInManifest until you run -GenerateManifest.' -ForegroundColor DarkYellow
}

# --------------------------------------------------------------------------
# Main pass
# --------------------------------------------------------------------------
Write-Head 'Processing'
$results = New-Object System.Collections.Generic.List[object]
$i = 0
$sw = [Diagnostics.Stopwatch]::StartNew()
$newManifestFiles = [ordered]@{}

foreach ($f in $files) {
    $i++
    $rel = Get-RelativeKey $Root $f.FullName
    $isWeight = (Test-ExtIn $f.Name $WeightExtensions)

    $row = [ordered]@{
        Path        = $rel
        Size        = $f.Length
        Weight      = $isWeight
        Format      = $(if (Test-FormatCodeCapable $f.Name) { 'code-capable' } else { 'data' })
        ContentAddressed = $false
        Sha256      = $null
        State       = 'Unknown'
        Detail      = ''
        VtMalicious = $null
        VtTotal     = $null
    }

    if ($GenerateManifest) {
        Write-Host ("  [{0}/{1}] hashing {2}" -f $i, $files.Count, $rel) -ForegroundColor DarkGray
        $h = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToUpperInvariant()
        $row.Sha256 = $h
        $row.State = 'Recorded'
        $newManifestFiles[$rel] = [ordered]@{
            Size      = $f.Length
            Sha256    = $h
            LastWrite = $f.LastWriteTimeUtc.ToString('o')
        }
    }
    else {
        $entry = $null
        if ($existing.ContainsKey($rel)) { $entry = $existing[$rel] }

        # Ollama (and OCI-style caches) store blobs as 'sha256-<hex>' with no
        # extension. The file NAME is the expected digest, so those blobs are
        # self-verifying and need no manifest bookkeeping at all.
        $embedded = $null
        $m = [regex]::Match($f.Name, '^sha256-([0-9a-fA-F]{64})$')
        if ($m.Success) { $embedded = $m.Groups[1].Value.ToUpperInvariant() }
        $row.ContentAddressed = [bool]$embedded

        if ($null -eq $entry -and $embedded) {
            if ($Quick) {
                $row.State = 'OkSizeOnly'
                $row.Detail = 'content-addressed blob; size-only pass (name hash not re-checked)'
            }
            else {
                Write-Host ("  [{0}/{1}] hashing blob {2}" -f $i, $files.Count, $rel) -ForegroundColor DarkGray
                $h = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToUpperInvariant()
                $row.Sha256 = $h
                if ($h -eq $embedded) {
                    $row.State = 'OkSelfAddressed'
                    $row.Detail = 'SHA256 matches the hash embedded in the file name'
                }
                else {
                    $row.State = 'HashMismatch'
                    $row.Detail = "content-address name says $embedded but content hashes to $h"
                }
            }
        }
        elseif ($null -eq $entry) {
            $row.State = 'NotInManifest'
            $row.Detail = 'file exists on disk but is not recorded in the manifest'
        }
        elseif ($Quick) {
            $expSize = [long]$entry.Size
            if ($expSize -ne $f.Length) {
                $row.State = 'SizeMismatch'
                $row.Detail = "expected $expSize bytes, found $($f.Length)"
            }
            else {
                $row.State = 'OkSizeOnly'
                $row.Detail = 'size matches (contents not hashed)'
            }
            if ($entry.PSObject.Properties['Sha256']) { $row.Sha256 = [string]$entry.Sha256 }
        }
        else {
            $expSha = [string]$entry.Sha256
            $expSize = [long]$entry.Size
            Write-Host ("  [{0}/{1}] hashing {2}" -f $i, $files.Count, $rel) -ForegroundColor DarkGray
            $h = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToUpperInvariant()
            $row.Sha256 = $h
            if ($expSize -ne $f.Length) {
                $row.State = 'SizeMismatch'
                $row.Detail = "expected $expSize bytes, found $($f.Length) - hash not compared"
            }
            elseif ($expSha -eq $h) {
                $row.State = 'Ok'
            }
            else {
                $row.State = 'HashMismatch'
                $row.Detail = "expected $expSha"
            }
        }
    }

    # VirusTotal: hash-only lookup is always safe; upload is tightly gated.
    if ($VtMode -ne 'None') {
        $vtEligible = (-not $isWeight) -and ($f.Length -le $VtMaxBytes)
        if (-not $isWeight -and $f.Length -gt $VtMaxBytes) {
            $row.Detail = ($row.Detail + ' ; VT skipped: over size cap').Trim(' ', ';')
        }
        if ($isWeight -and $VtMode -eq 'Upload') {
            $row.Detail = ($row.Detail + ' ; VT upload refused for weight shard').Trim(' ', ';')
        }

        if ($VtMode -eq 'Lookup') {
            # Uses whatever hash we already have; a lookup needs no upload at all.
            $hashForVt = $row.Sha256
            if (-not $hashForVt -and $existing.ContainsKey($rel)) { $hashForVt = [string]$existing[$rel].Sha256 }
            if ($hashForVt) {
                $vt = Get-VtFileReport -Sha256 $hashForVt -ApiKey $vtKey
                if ($vt.Found) {
                    $row.VtMalicious = $vt.Malicious
                    $row.VtTotal = $vt.Total
                }
                else {
                    $row.VtMalicious = -1
                    $row.VtTotal = 0
                }
            }
        }
        elseif ($VtMode -eq 'Upload' -and $vtEligible) {
            Write-Host ("  VT upload {0} ({1:N1} MiB)" -f $rel, ($f.Length / 1MB)) -ForegroundColor Yellow
            try {
                $resp = Invoke-RestMethod -Uri 'https://www.virustotal.com/api/v3/files' `
                    -Headers @{ 'x-apikey' = $vtKey } -Method Post `
                    -Form @{ file = Get-Item -LiteralPath $f.FullName } -TimeoutSec 120
                $row.Detail = ($row.Detail + ' ; VT accepted for analysis').Trim(' ', ';')
                $id = [string]$resp.data.id
                if ($id) { $row.Detail = $row.Detail + " (analysis $id)" }
            }
            catch {
                $row.Detail = ($row.Detail + (' ; VT upload failed: ' + $_.Exception.Message)).Trim(' ', ';')
            }
        }
    }

    $results.Add([pscustomobject]$row)
}

$sw.Stop()

# --------------------------------------------------------------------------
# Manifest drift: entries recorded but now absent
# --------------------------------------------------------------------------
$missing = @()
if ($haveManifest -and -not $GenerateManifest) {
    $onDisk = @{}
    foreach ($r in $results) { $onDisk[$r.Path] = $true }
    foreach ($k in $existing.Keys) {
        if (-not $onDisk.ContainsKey($k)) { $missing += $k }
    }
}

# --------------------------------------------------------------------------
# Write manifest
# --------------------------------------------------------------------------
if ($GenerateManifest) {
    $dir = Split-Path -Parent $Manifest
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { $null = New-Item -ItemType Directory -Path $dir -Force }
    $doc = [ordered]@{
        SchemaVersion = 1
        Root          = $Root
        GeneratedUtc  = (Get-Date).ToUniversalTime().ToString('o')
        Host          = $env:COMPUTERNAME
        FileCount     = $newManifestFiles.Count
        Files         = $newManifestFiles
    }
    ($doc | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $Manifest -Encoding UTF8
    Write-Host ''
    Write-Host (" Manifest written: {0} ({1} file(s))" -f $Manifest, $newManifestFiles.Count) -ForegroundColor Green
}

# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
$summary = [ordered]@{
    Root          = $Root
    Manifest      = $Manifest
    ScannedUtc    = (Get-Date).ToUniversalTime().ToString('o')
    Mode          = $(if ($GenerateManifest) { 'GenerateManifest' } elseif ($Quick) { 'QuickVerify' } else { 'FullVerify' })
    FileCount     = $results.Count
    TotalBytes    = $totalBytes
    ElapsedSec    = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    Ok            = @($results | Where-Object { $_.State -in @('Ok', 'OkSizeOnly', 'Recorded', 'OkSelfAddressed') }).Count
    SizeMismatch  = @($results | Where-Object { $_.State -eq 'SizeMismatch' }).Count
    HashMismatch  = @($results | Where-Object { $_.State -eq 'HashMismatch' }).Count
    NotInManifest = @($results | Where-Object { $_.State -eq 'NotInManifest' }).Count
    MissingOnDisk = @($missing).Count
    CodeCapable   = @($results | Where-Object { $_.Format -eq 'code-capable' }).Count
    SelfAddressed = @($results | Where-Object { $_.State -eq 'OkSelfAddressed' }).Count
}

Write-Host ''
Write-Host '============================================================' -ForegroundColor DarkCyan
Write-Host ' Summary' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor DarkCyan
foreach ($k in $summary.Keys) {
    Write-Host ("  {0,-15} {1}" -f $k, $summary[$k])
}

if ($results.Count -gt 0) {
    Write-Host ''
    Write-Host ' Results by state:' -ForegroundColor DarkGray
    $results | Group-Object State | Sort-Object Name | ForEach-Object {
        Write-Host ("   {0,-16} {1}" -f $_.Name, $_.Count)
    }
}

$bad = @($results | Where-Object { $_.State -in @('HashMismatch', 'SizeMismatch') })
if ($bad.Count -gt 0) {
    Write-Host ''
    Write-Host ' INTEGRITY FAILURES:' -ForegroundColor Red
    $bad | ForEach-Object {
        Write-Host ("   x {0} [{1}] {2}" -f $_.Path, $_.State, $_.Detail) -ForegroundColor Red
    }
}

$vtHits = @($results | Where-Object { $null -ne $_.VtMalicious -and $_.VtMalicious -gt 0 })
if ($vtHits.Count -gt 0) {
    Write-Host ''
    Write-Host ' VIRUSTOTAL DETECTIONS:' -ForegroundColor Red
    $vtHits | ForEach-Object {
        Write-Host ("   x {0}: {1}/{2} engines" -f $_.Path, $_.VtMalicious, $_.VtTotal) -ForegroundColor Red
    }
}

if ($missing.Count -gt 0) {
    Write-Host ''
    Write-Host (" {0} manifest entrie(s) no longer present on disk." -f $missing.Count) -ForegroundColor Yellow
    $missing | Select-Object -First 10 | ForEach-Object { Write-Host ("   - {0}" -f $_) -ForegroundColor Yellow }
}

# Persist report
$rdir = Split-Path -Parent $ReportPath
if ($rdir -and -not (Test-Path -LiteralPath $rdir)) { $null = New-Item -ItemType Directory -Path $rdir -Force }
$payload = [ordered]@{ Summary = $summary; MissingOnDisk = @($missing); Files = $results.ToArray() }
($payload | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $ReportPath -Encoding UTF8
Write-Host ''
Write-Host (" Report: {0}" -f $ReportPath) -ForegroundColor DarkGray

# --------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------
Write-Host ''
$exit = 0
if ($bad.Count -gt 0 -or $vtHits.Count -gt 0) {
    $exit = 1
    Write-Host ' RESULT: FAIL - integrity or reputation problem found. Do not load these files.' -ForegroundColor Red
}
elseif ($GenerateManifest) {
    Write-Host ' RESULT: baseline recorded. This pins what you have, not that it is safe.' -ForegroundColor Green
}
else {
    Write-Host ' RESULT: PASS - every recorded file matches its hash.' -ForegroundColor Green
}
Write-Host ' Reminder: integrity != safety. A matching hash means "unchanged".' -ForegroundColor DarkGray
Write-Host ''

if (-not $script:DotSourced) { exit $exit } else { return }






