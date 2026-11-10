<#
  preflight.ps1 - will this machine run DeepSeek-V4.1-Flash-1017, and what will the
  library cost? Reads only. Changes nothing. No downloads.

  The thresholds come from Strata's own documentation and planner:
    - >= 8 GiB VRAM minimum, 12 GiB as measured (dense weights are VRAM-resident)
    - 46-64 GiB RAM for the 2.00 bpw set; below ~40 GiB is untested and slow
    - NVMe strongly preferred: the 103 GiB Engram table is read every token
#>
[CmdletBinding()]
param(
  [string]$ProjectRoot = '',
  [string]$LibraryRoot = "$env:USERPROFILE\Models\huggingface\AtomicChat--DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF"
)

$ErrorActionPreference = 'SilentlyContinue'
if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }

$OK   = 'PASS'
$WARN = 'WARN'
$FAIL = 'FAIL'
$rows = @()
function Add-Row($check, $verdict, $detail) { $script:rows += [pscustomobject]@{ Check = $check; Verdict = $verdict; Detail = $detail } }

# --- GPU -------------------------------------------------------------------
# WMI's AdapterRAM is a 32-bit field and caps at 4 GiB, so an RTX 2060 6 GB reads
# as "4 GB" there. nvidia-smi is authoritative when present.
$smi = (Get-Command nvidia-smi -ErrorAction SilentlyContinue).Source
$gpuName = 'none'; $bestVram = 0; $compute = $null; $driver = $null
if ($smi) {
  $line = & $smi --query-gpu=name,memory.total,driver_version,compute_cap --format=csv,noheader 2>$null | Select-Object -First 1
  if ($line) {
    $f = $line -split ',\s*'
    $gpuName  = $f[0]
    $bestVram = [double]($f[1] -replace '[^0-9.]', '') / 1024
    $driver   = $f[2]
    $compute  = $f[3]
  }
}
if (-not $bestVram) {
  $cards = @(Get-CimInstance Win32_VideoController | Where-Object { $_.Name -notmatch 'Basic|Remote' })
  foreach ($c in $cards) {
    $v = if ($c.AdapterRAM) { [double]$c.AdapterRAM / 1GB } else { 0 }
    if ($v -gt $bestVram) { $bestVram = $v; $gpuName = $c.Name }
  }
}
$turing = ($compute -eq '7.5') -or ($gpuName -match 'RTX\s+20|GTX\s+16|Quadro\s+T')
if ($bestVram -ge 11)      { Add-Row 'VRAM' $OK   ("{0:N1} GiB on {1} (compute {2}, driver {3})" -f $bestVram, $gpuName, $compute, $driver) }
elseif ($bestVram -ge 8)   { Add-Row 'VRAM' $WARN ("{0:N1} GiB on {1} - at the documented minimum; expect --speed faster and short context" -f $bestVram, $gpuName) }
else                       { Add-Row 'VRAM' $FAIL ("{0:N1} GiB on {1} - below the 8 GiB floor; the engine will stop at start" -f $bestVram, $gpuName) }
if ($turing -and $gpuName -match 'NVIDIA|GeForce|RTX|GTX|Quadro') {
  Add-Row 'CUDA_ARCH' $WARN ("Turing (sm_{0}): the prebuilt DeepSeek engine ships sm_86/89/120 only; a self-build is required even with enough VRAM" -f ($compute -replace '\.',''))
}

# --- RAM -------------------------------------------------------------------
$ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$ramVerdict = if ($ram -ge 64) { $OK } elseif ($ram -ge 46) { $WARN } else { $FAIL }
Add-Row 'RAM' $ramVerdict ("{0:N1} GiB total - the vendor's reference boxes are 46-64 GiB for the 2.00 bpw set" -f $ram)

# --- disk ------------------------------------------------------------------
$free = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
Add-Row 'DISK_FREE' (if ($free -ge 400) { $OK } elseif ($free -ge 360) { $WARN } else { $FAIL }) ("{0:N1} GiB free on C: - the full library is 352.5 GiB" -f $free)
$disk = Get-PhysicalDisk | Where-Object { $_.MediaType } | Sort-Object Size -Descending | Select-Object -First 1
Add-Row 'DISK_TYPE' (if ($disk.MediaType -eq 'SSD') { $OK } else { $WARN }) ("{0} ({1})" -f $disk.FriendlyName, $disk.MediaType)

# --- CPU -------------------------------------------------------------------
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
Add-Row 'CPU' $OK ("{0} - {1} cores / {2} threads" -f $cpu.Name.Trim(), $cpu.NumberOfCores, $cpu.NumberOfLogicalProcessors)

# --- runtime ---------------------------------------------------------------
$strata = Get-Command strata.cmd -ErrorAction SilentlyContinue
if (-not $strata) { $strata = Get-Command strata -ErrorAction SilentlyContinue }
Add-Row 'STRATA' (if ($strata) { $OK } else { $WARN }) ($(if ($strata) { (Split-Path $strata.Source -Parent) } else { 'not installed - Tools/runtime/install-strata.ps1' }))

# --- library ---------------------------------------------------------------
$files = @(Get-ChildItem $LibraryRoot -Recurse -File -ErrorAction SilentlyContinue)
$present = ($files | Measure-Object Length -Sum).Sum
if (-not $present) { $present = 0 }
$libVerdict = if ($present -ge 352.4GB) { $OK } elseif ($present -gt 0) { $WARN } else { $FAIL }
Add-Row 'LIBRARY' $libVerdict ("{0:N1} GiB present in {1}" -f ($present / 1GB), $LibraryRoot)

# --- report ----------------------------------------------------------------
Write-Host ''
Write-Host 'DeepSeek-V4.1-Flash-1017 power stack :: preflight' -ForegroundColor Cyan
Write-Host ('-' * 78)
$rows | Format-Table -AutoSize Check, Verdict, Detail | Out-String | Write-Host

$hardFail = @($rows | Where-Object { $_.Verdict -eq $FAIL -and $_.Check -in @('VRAM', 'CUDA_ARCH', 'RAM') })
Write-Host ''
if ($hardFail.Count -gt 0) {
  Write-Host 'VERDICT: this machine cannot execute the model.' -ForegroundColor Red
  Write-Host ('  blocked by: ' + (($hardFail | ForEach-Object { $_.Check }) -join ', '))
  Write-Host '  Acquiring + verifying the library still works here; running it needs >= 12 GiB VRAM'
  Write-Host '  and >= 48 GiB RAM (see Docs/library/HARDWARE.md for the exact numbers).'
  Write-Host '  Cloud path: cloud/README.md (rent an sm_89/sm_120 card, keep the client here).'
} else {
  Write-Host 'VERDICT: hardware is in range.' -ForegroundColor Green
  Write-Host '  Next: Tools/runtime/fetch-library.ps1 -> scripts/verify_library.py -> Tools/runtime/run.ps1'
}
Write-Host ''
exit ([int]($hardFail.Count -gt 0))
