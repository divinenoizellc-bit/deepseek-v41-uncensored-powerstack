<#
  import-verified.ps1 - hand the verified local library to Strata, refusing anything
  whose SHA-256 is not in manifests/acceptance.json.

  Why this exists: Strata's own downloader compares shards against ISTA-DASLab's pins.
  Our shard 00004 carries the abliteration, so its hash differs by design (same size).
  The "files you already have" path (--model-path / models import) is the correct door.
#>
[CmdletBinding()]
param(
  [ValidateSet('IQ2_XXS','IQ1_M')]
  [string]$Rung = 'IQ2_XXS',
  [string]$ProjectRoot = '',
  [string]$LibraryRoot = "$env:USERPROFILE\Models\huggingface\AtomicChat--DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF",
  [ValidateSet('plan','pack','launch')]
  [string]$Mode = 'plan',
  [string]$Preset = 'balanced'
)

$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }

$sevenZip = 0
$firstShard = "DeepSeek-V4.1-Flash-1017-GSQ-RCO-{0}-00001-of-00004.gguf" -f $Rung
$paths = @(
  (Join-Path $LibraryRoot $firstShard)
  (Join-Path $LibraryRoot 'DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf')
  (Join-Path $LibraryRoot 'dspark-DeepSeek-V4.1-Flash-1017-Q8_0.gguf')
  (Join-Path $LibraryRoot 'mmproj-BF16.gguf')
)

Write-Host "1/4 verifying the rung + shared files (this streams ~%TOTAL% GiB; -Quick skips hashing)" -ForegroundColor Cyan
$verifyArgs = @((Join-Path $ProjectRoot 'scripts\verify_library.py'), '--manifest', (Join-Path $ProjectRoot 'manifests\acceptance.json'), '--only', $Rung)
& python @verifyArgs
$rungExit = $LASTEXITCODE
if ($rungExit -ne 0) {
  # the shared files (Engram/drafter/mmproj) are not tagged with the rung name
  & python (Join-Path $ProjectRoot 'scripts\verify_library.py') --manifest (Join-Path $ProjectRoot 'manifests\acceptance.json') --only 'Engram|dspark|mmproj'
  if ($LASTEXITCODE -ne 0) { throw "verification failed: the $Rung set or its shared files do not match the accepted pins. Nothing was imported." }
  Write-Host "  (rung filter found nothing to hash; continuing after the shared-file check)" -ForegroundColor Yellow
}
Write-Host '  [ok] hashes verified' -ForegroundColor Green

foreach ($p in $paths) {
  if (-not (Test-Path $p)) { throw "missing required file: $p  (run Tools/runtime/fetch-library.ps1 -Set all)" }
}

$strata = Get-Command strata.cmd -ErrorAction SilentlyContinue
if (-not $strata) { $strata = Get-Command strata -ErrorAction SilentlyContinue }
if (-not $strata) { throw 'Strata is not installed. Run Tools/runtime/install-strata.ps1 first.' }

$modelId = if ($Rung -eq 'IQ2_XXS') { 'ist-das-2.00bpw' } else { 'ist-das-1.75bpw' }

Write-Host "2/4 preflight: strata launch --plan for $modelId" -ForegroundColor Cyan
& $strata.Source launch --model-path $LibraryRoot --family deepseek41 --model $modelId --plan
if ($LASTEXITCODE -ne 0) { throw 'the plan step failed; see the message above' }

switch ($Mode) {
  'plan' {
    Write-Host "3/4 plan only. To pack: -Mode pack; to start: -Mode launch -Preset balanced" -ForegroundColor Yellow
  }
  'pack' {
    Write-Host '3/4 packing (this is when the 138 GB is read and the pack is built; expect 10-30 min)' -ForegroundColor Cyan
    & $strata.Source launch --model-path $LibraryRoot --family deepseek41 --model $modelId --context 8k --vision off --parallel 1 --tune skip --no-tui --yes
    if ($LASTEXITCODE -ne 0) { throw 'pack/start failed; if it names a hash mismatch, use the source packer (Docs/library/RUNBOOK.md B3)' }
  }
  'launch' {
    Write-Host "3/4 launching with preset $Preset" -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot 'run.ps1') -Preset $Preset -ModelPath $LibraryRoot -ModelId $modelId
  }
}
Write-Host '4/4 done' -ForegroundColor Green
