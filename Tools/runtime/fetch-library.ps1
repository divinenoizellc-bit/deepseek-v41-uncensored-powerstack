<#
  fetch-library.ps1 - resumable, pinned, verified fetch of the DeepSeek-V4.1-Flash-1017
  uncensored power-stack library.

  Every file comes from a pinned Hugging Face revision. hf-xet keeps its own chunk
  cache, so re-running this script after an interruption continues where it stopped.

  Order is deliberate:
    1. the small shared trio   (pins + metadata, ~1 GB, seconds)
    2. IQ2_XXS (2.00 bpw)      the rung that passed every gate in the model card
    3. the shared Engram table (103 GiB, needed by every rung)
    4. the DSpark drafter      (8 GiB, faster answers once a GPU can run it)
    5. IQ1_M (1.75 bpw)        the smallest rung, also gate-passing
  IQ2_XS (2.25 bpw) is deliberately skipped: its rung is published as FAILED in
  cards/rungs.json (pass: false) and it costs another 145 GiB.

  Usage:  pwsh -File fetch-library.ps1 [-Set IQ2_XXS|IQ1_M|shared|all] [-DryRun]
#>
[CmdletBinding()]
param(
  [ValidateSet('all','shared','IQ2_XXS','IQ1_M')]
  [string]$Set = 'all',
  [string]$LibraryRoot = "$env:USERPROFILE\Models\huggingface\AtomicChat--DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF",
  [string]$ProjectRoot = '',
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

if (-not $ProjectRoot) {
  $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}

# --- pins (verified against the HF API tree and Strata's own setup.py) ------------------
$PINS = @{
  Uncensored = @{
    Repo = 'AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF'
    Rev  = '4f1d2f730cff977961db81789e81bfc0d3e6dd2e'
  }
  Base = @{
    Repo = 'ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF'
    Rev  = 'cb02422c900df489cea5833e8a92171224059b3c'
  }
  Unsloth = @{
    Repo = 'unsloth/DeepSeek-V4.1-Flash-1017-GGUF'
    Rev  = '8a6ec9cf118e785a362ea94ee123c61c70553be6'
  }
}

$logDir = Join-Path $ProjectRoot 'Library\logs'
New-Item -ItemType Directory -Force -Path $LibraryRoot, $logDir | Out-Null

function Get-FreeGiB {
  (Get-PSDrive C).Free / 1GB
}

function Needs-Space([double]$GiB, [string]$What) {
  $free = Get-FreeGiB
  if ($free -lt ($GiB + 40)) {
    throw ("not enough space for {0}: needs {1:N1} GiB + 40 GiB headroom, {2:N1} GiB free" -f $What, $GiB, $free)
  }
  Write-Host ("  space ok: {0:N1} GiB free, this step needs {1:N1} GiB" -f $free, $GiB)
}

function Invoke-Hf([hashtable]$pin, [string[]]$include, [string]$What, [double]$GiB) {
  Needs-Space $GiB $What
  $args = @(
    'download', $pin.Repo,
    '--revision', $pin.Rev,
    '--local-dir', $LibraryRoot,
    '--max-workers', '4'
  )
  foreach ($p in $include) { $args += '--include'; $args += $p }

  Write-Host ("==> {0}  ({1} @ {2})" -f $What, $pin.Repo, $pin.Rev.Substring(0,12))
  Write-Host ("    hf " + ($args -join ' '))
  if ($DryRun) { return }

  $started = Get-Date
  & hf @args 2>&1 | ForEach-Object {
    if ($_ -match 'Fetching|Downloading|\.part|it/s|B/s|Error') { Write-Host "    $_" }
    $_
  } | Out-File -Append -Encoding utf8 (Join-Path $logDir 'fetch-library.log')
  if ($LASTEXITCODE -ne 0) { throw "hf download failed for $What (exit $LASTEXITCODE) - re-run to resume" }
  $mins = ((Get-Date) - $started).TotalMinutes
  Write-Host ("    done in {0:N0} min" -f $mins)
  Clear-XetCache
  Show-Progress
}

function Show-Progress {
  $files = Get-ChildItem $LibraryRoot -Recurse -File -ErrorAction SilentlyContinue
  $bytes = ($files | Measure-Object Length -Sum).Sum
  if (-not $bytes) { $bytes = 0 }
  Write-Host ("-- library: {0:N2} GiB in {1} files, {2:N1} GiB free" -f ($bytes/1GB), $files.Count, (Get-FreeGiB))
}

# hf-xet holds chunks in a cache while it assembles a 40 GB shard: peak usage is
# roughly 2x the file. Once the file is renamed into place the chunks are dead
# weight, so reclaim them - otherwise the full 352.5 GiB library needs ~700 GiB.
function Clear-XetCache {
  $caches = @(
    (Join-Path $env:USERPROFILE '.cache\huggingface\xet'),
    (Join-Path $env:LOCALAPPDATA 'huggingface\xet')
  )
  foreach ($c in $caches) {
    if (Test-Path $c) {
      $before = (Get-ChildItem $c -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
      Get-ChildItem $c -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
      Write-Host ("  reclaimed {0:N2} GiB from {1}" -f ($before/1GB), $c)
    }
  }
  # dead .incomplete / .lock files from interrupted runs
  $dl = Join-Path $LibraryRoot '.cache\huggingface\download'
  if (Test-Path $dl) {
    Get-ChildItem $dl -File -Force -ErrorAction SilentlyContinue |
      Where-Object { $_.Length -eq 0 -and ($_.Name -like '*.incomplete' -or $_.Name -like '*.lock') } |
      Remove-Item -Force -ErrorAction SilentlyContinue
  }
}

Write-Host "DeepSeek-V4.1-Flash-1017 uncensored power-stack :: library fetch"
Write-Host "library: $LibraryRoot"
Show-Progress

if ($Set -in @('all','shared')) {
  # 1. mmproj (vision tower) + the metadata shard pack_gguf --engram-meta reads
  Invoke-Hf $PINS.Unsloth @('mmproj-BF16.gguf','UD-Q8_K_XL/DeepSeek-V4.1-Flash-1017-UD-Q8_K_XL-00001-of-00009.gguf') 'shared support files (vision tower + engram metadata)' 1.0
  # 1b. the four text artifacts the manifest pins (license, card, rungs, attributes)
  Invoke-Hf $PINS.Uncensored @('.gitattributes','LICENSE','README.md','cards/*') 'text artifacts (license, card, rung scorecard)' 0.01
}

if ($Set -in @('all','IQ2_XXS')) {
  # 2. the gate-passing 2.00 bpw rung
  Invoke-Hf $PINS.Uncensored @('*IQ2_XXS*') 'IQ2_XXS rung (2.00 bpw, 4 shards)' 128.9
}

if ($Set -in @('all','shared')) {
  # 3. the 103 GiB Engram table every rung reads
  Invoke-Hf $PINS.Base @('*Engram-IQ4_NL*') 'shared Engram table (IQ4_NL)' 103.0
  # 4. the DSpark drafter (Strata's default --dspark auto uses it)
  Invoke-Hf $PINS.Unsloth @('dspark-DeepSeek-V4.1-Flash-1017-Q8_0.gguf') 'DSpark drafter (Q8_0)' 7.5
}

if ($Set -in @('all','IQ1_M')) {
  # 5. the smallest gate-passing rung
  Invoke-Hf $PINS.Uncensored @('*IQ1_M*') 'IQ1_M rung (1.75 bpw, 4 shards)' 112.5
}

Show-Progress
Write-Host 'verify with:  python scripts\verify_library.py'
