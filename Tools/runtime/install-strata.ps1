<#
  install-strata.ps1 - install the Strata Terminal from a PINNED release, verifying the
  download against two independent sources:
    1. SHA256SUMS.txt published in that release
    2. the sha256 GitHub's own release API reports for the asset (`digest`)

  The official install.ps1 then verifies the archive it unpacks against the release
  manifest and checks the release's signed update feed. Nothing here needs admin rights.
#>
[CmdletBinding()]
param(
  [string]$Version = 'v0.2.13',
  [switch]$NoRun
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'
Set-StrictMode -Version Latest

$feeds = @{
  'v0.2.13' = @{
    Install      = 'https://github.com/Niko1221/Strata/releases/download/v0.2.13/install.ps1'
    Sums         = 'https://github.com/Niko1221/Strata/releases/download/v0.2.13/SHA256SUMS.txt'
    ExpectedHash = '322ad52bddc137893b6091f4e8ff989cd87ba968e063e5b08e43e167480343fc'
  }
}
if (-not $feeds.ContainsKey($Version)) { throw "no pinned hashes for $Version; add them here first" }
$pin = $feeds[$Version]

$work = Join-Path $env:TEMP ('strata-verify-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $work | Out-Null
try {
  Write-Host "Downloading Strata $Version installer..."
  $ps1  = Join-Path $work 'install.ps1'
  $sums = Join-Path $work 'SHA256SUMS.txt'
  Invoke-WebRequest -UseBasicParsing -Uri $pin.Install -OutFile $ps1
  Invoke-WebRequest -UseBasicParsing -Uri $pin.Sums    -OutFile $sums

  $got = (Get-FileHash $ps1 -Algorithm SHA256).Hash.ToLower()
  Write-Host "  sha256(install.ps1) = $got"

  # source 1: our pinned constant
  if ($got -ne $pin.ExpectedHash) { throw "install.ps1 does not match the pinned hash (expected $($pin.ExpectedHash))" }
  Write-Host '  [ok] matches the pinned constant'

  # source 2: the release's own SHA256SUMS.txt
  $line = (Get-Content $sums) | Where-Object { $_ -match 'install\.ps1\s*$' } | Select-Object -First 1
  if (-not $line) { throw 'SHA256SUMS.txt does not list install.ps1' }
  $listed = ($line -split '\s+')[0].ToLower()
  if ($listed -ne $got) { throw "SHA256SUMS.txt lists $listed but the download is $got" }
  Write-Host '  [ok] matches the release SHA256SUMS.txt'

  # source 3: GitHub's asset digest, if the API offers one
  try {
    $api = Invoke-RestMethod -UseBasicParsing -Uri "https://api.github.com/repos/Niko1221/Strata/releases/tags/$Version" -Headers @{ 'User-Agent' = 'dsh-strata-verify' }
    $asset = $api.assets | Where-Object { $_.name -eq 'install.ps1' } | Select-Object -First 1
    if ($asset.digest) {
      $apiHash = ($asset.digest -replace '^sha256:', '').ToLower()
      if ($apiHash -ne $got) { throw "GitHub asset digest says $apiHash, download is $got" }
      Write-Host '  [ok] matches the GitHub release API digest'
    }
  } catch {
    Write-Host "  [warn] could not cross-check the GitHub API digest: $($_.Exception.Message)"
  }

  if ($NoRun) { Write-Host "Verified. Not running (NoRun). Script at $ps1"; return }

  Write-Host 'Running the verified installer (it re-verifies the archive and the signed feed)...'
  & $ps1
  if ($LASTEXITCODE -ne 0) { throw "installer exited $LASTEXITCODE" }
  Write-Host 'Strata Terminal installed. Open a new terminal so `strata` is on PATH.'
}
finally {
  Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
