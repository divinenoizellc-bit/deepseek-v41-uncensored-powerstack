<#
  run.ps1 - launch DeepSeek-V4.1-Flash-1017 with a named power preset.
  Refuses to start (with the reason) when the machine cannot hold the dense weights.

  Presets: nuclear | balanced | code | smoke | throughput
  See Docs/library/POWER.md for what each one spends.
#>
[CmdletBinding()]
param(
  [ValidateSet('nuclear','balanced','code','smoke','throughput','custom')]
  [string]$Preset = 'balanced',
  [string]$ModelPath = "$env:USERPROFILE\Models\huggingface\AtomicChat--DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF",
  [ValidateSet('ist-das-2.00bpw','ist-das-1.75bpw')]
  [string]$ModelId = 'ist-das-2.00bpw',
  [string]$DataDir = '',
  [string]$Access = 'local',
  [int]$Port = 8080,
  [switch]$Force,
  [switch]$NoTui,
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Extra
)

$ErrorActionPreference = 'Stop'

# --- refuse politely --------------------------------------------------------
$cards = @(Get-CimInstance Win32_VideoController | Where-Object { $_.Name -notmatch 'Basic|Remote' })
$bestVram = 0; $bestName = 'none'
foreach ($c in $cards) {
  $v = if ($c.AdapterRAM) { $c.AdapterRAM / 1GB } else { 0 }
  if ($v -gt $bestVram) { $bestVram = $v; $bestName = $c.Name }
}
$ram = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB
Write-Host ("host: {0:N1} GiB VRAM ({1}), {2:N1} GiB RAM" -f $bestVram, $bestName, $ram) -ForegroundColor DarkGray
if (-not $Force -and $bestVram -lt 7.5) {
  Write-Host ''
  Write-Host 'REFUSING TO START: this model needs >= 8 GiB VRAM (12 GiB measured).' -ForegroundColor Red
  Write-Host ("  found: {0:N1} GiB. The dense weights (~16.8 GB) must be VRAM-resident, so the" -f $bestVram)
  Write-Host '  engine stops at start regardless of context or experts flags.'
  Write-Host '  See Docs/library/HARDWARE.md, or run on a rented GPU: cloud/README.md'
  Write-Host '  Override with -Force only if you are on a machine with a usable card.'
  exit 3
}

# --- presets ----------------------------------------------------------------
$presets = @{
  nuclear    = @('--context','1m','--speed','full','--parallel','8','--vision','on','--kv','int8','--tune','thorough','--set','prefill=65536')
  balanced   = @('--context','128k','--speed','full','--parallel','4','--vision','off','--kv','int8','--tune','quick')
  code       = @('--context','64k','--speed','full','--parallel','2','--vision','off','--kv','q4_0','--tune','skip')
  smoke      = @('--context','8k','--speed','faster','--parallel','1','--vision','off','--kv','q4_0','--tune','skip')
  throughput = @('--context','32k','--speed','full','--parallel','8','--vision','off','--kv','int8','--tune','skip','--dspark','on','--drafting','dflash2','--set','prefill=32768')
  custom     = @()
}
$args = @('launch','--family','deepseek41','--model',$ModelId,'--access',$Access,'--port',$Port)
$args += $presets[$Preset]
if ($ModelPath -and (Test-Path $ModelPath)) { $args += @('--model-path', $ModelPath) }
if ($DataDir) { $args += @('--data-dir', $DataDir) }
if ($NoTui) { $args += '--no-tui' }
if ($Extra) { $args += $Extra }

$strata = Get-Command strata.cmd -ErrorAction SilentlyContinue
if (-not $strata) { $strata = Get-Command strata -ErrorAction SilentlyContinue }
if (-not $strata) { throw 'Strata is not installed. Run Tools/runtime/install-strata.ps1.' }

Write-Host ''
Write-Host ("preset {0}: strata {1}" -f $Preset, ($args -join ' ')) -ForegroundColor Cyan
Write-Host ''
& $strata.Source @args
exit $LASTEXITCODE
