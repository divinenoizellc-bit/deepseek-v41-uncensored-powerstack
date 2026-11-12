#requires -Version 5.1
<#
  FINALIZE-SECURITY.ps1 — the one elevated pass that closes the findings from the
  security review. Preview by default; -Apply performs it. Reversible with -Revert
  for the parts that have a clean inverse.

  Findings it fixes (measured 2026-11-11 on this box):
    1. Windows Firewall is OFF on all three profiles, with 427 inbound-allow rules
       inert. Highest-severity finding of the whole review.
    2. Defender has PUA protection off, cloud/MAPS off, network protection off,
       Controlled Folder Access off, and 18 ASR rules unconfigured.
    3. "ProtonVPN WireGuard" service points at C:\Program Files\Proton\VPN\v5.1.7\…
       which the 5.1.9 upgrade deleted, so the fast protocol has been unavailable
       and the client silently fell back to OpenVPN.

  What it deliberately does NOT do:
    * It does not add firewall exceptions for RPC(135), SMB(445) or WSD(5357).
      Those are exactly the LAN exposures worth closing.
    * It does not add rules for services that only listen on loopback.
    * It does not touch browsing history, DNS, VPN accounts, or files.
    * It does not disable anything.

  Usage (elevated PowerShell):
      .\FINALIZE-SECURITY.ps1              # preview only, changes nothing
      .\FINALIZE-SECURITY.ps1 -Apply        # apply
      .\FINALIZE-SECURITY.ps1 -Apply -Revert # undo what -Apply changed
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [switch]$Apply,
  [switch]$Revert,
  [switch]$SkipDefender,
  [string]$StateDir = (Join-Path $PSScriptRoot '.state')
)

$ErrorActionPreference = 'Stop'
$TS = Get-Date -Format 'yyyyMMddTHHmmss'
$log = Join-Path $StateDir "finalize-security-$TS.log"
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
function Say([string]$m) { $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m; $line | Tee-Object -FilePath $log -Append | Write-Host }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Say "mode=$(if($Apply){'APPLY'}elseif($Revert){'REVERT'}else{'PREVIEW'}) elevated=$isAdmin"
if (($Apply -or $Revert) -and -not $isAdmin) { throw 'This script must run in an elevated PowerShell (Run as administrator).' }

# AnyDesk installs under Program Files (x86) on some builds; prefer the running binary.
$anydeskExe = $null
foreach ($cand in @((Join-Path $env:ProgramFiles 'AnyDesk\AnyDesk.exe'),
                    (Join-Path ${env:ProgramFiles(x86)} 'AnyDesk\AnyDesk.exe'))) {
  if ($cand -and (Test-Path $cand)) { $anydeskExe = $cand; break }
}
if (-not $anydeskExe) {
  $p = Get-Process AnyDesk -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($p -and $p.Path) { $anydeskExe = $p.Path }
}

# LAN-facing apps we keep reachable on the PRIVATE profile only.
# Public networks stay closed. Loopback-only services need no rule.
$lanApps = @(
  @{ Name = 'AnyDesk (LAN)';      Ports = @(7070);            Exe = $anydeskExe },
  @{ Name = 'Perforce p4s (LAN)'; Ports = @(1666);            Exe = $null },
  @{ Name = 'Unreal Editor (LAN)';Ports = @(1981,1985,1989,8558); Exe = $null },
  @{ Name = 'Local python server (LAN)'; Ports = @(8686);     Exe = $null }
)
function Get-LanRuleName($app) { "DSH LAN allow - $($app.Name)" }

# ---------------------------------------------------------------- snapshot
$snap = [ordered]@{
  capturedAt = (Get-Date).ToString('o')
  firewall = @(Get-NetFirewallProfile | Select-Object Name, Enabled, DefaultInboundAction, DefaultOutboundAction)
  wireguardService = (Get-CimInstance Win32_Service -Filter "Name='ProtonVPN WireGuard'" | Select-Object Name, PathName, StartMode)
  defender = @{ PUAProtection = (Get-MpPreference).PUAProtection; MAPSReporting = (Get-MpPreference).MAPSReporting
                EnableNetworkProtection = (Get-MpPreference).EnableNetworkProtection
                EnableControlledFolderAccess = (Get-MpPreference).EnableControlledFolderAccess }
}
$snapFile = Join-Path $StateDir "finalize-security-$TS.before.json"
$snap | ConvertTo-Json -Depth 5 | Set-Content $snapFile -Encoding UTF8
Say "backup: $snapFile"

# ---------------------------------------------------------------- revert
if ($Revert) {
  Say 'restoring firewall profiles from the newest backup with a firewall section'
  $newest = Get-ChildItem $StateDir -Filter 'finalize-security-*.before.json' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if ($newest) {
    $old = Get-Content $newest.FullName -Raw | ConvertFrom-Json
    foreach ($p in $old.firewall) {
      if ($p.Enabled -ne $true) {
        if ($PSCmdlet.ShouldProcess($p.Name, 'disable firewall profile (restore)')) {
          Set-NetFirewallProfile -Profile $p.Name -Enabled $false
          Say "  $($p.Name): firewall -> disabled (as before)"
        }
      }
    }
    if ($old.wireguardService.PathName) {
      if ($PSCmdlet.ShouldProcess('ProtonVPN WireGuard', 'restore original service path')) {
        $svc = Get-CimInstance Win32_Service -Filter "Name='ProtonVPN WireGuard'"
        $res = Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{ PathName = $old.wireguardService.PathName }
        if ($res.ReturnValue -ne 0) { throw "service Change returned $($res.ReturnValue)" }
        Say "  WireGuard service path restored"
      }
    }
  } else { Say '  no backup found; nothing reverted' }
  Get-ChildItem $StateDir -Filter 'DSH LAN allow - *.lnk' -ErrorAction SilentlyContinue | Out-Null
  Get-NetFirewallRule -DisplayName 'DSH LAN allow -*' -ErrorAction SilentlyContinue | ForEach-Object {
    if ($PSCmdlet.ShouldProcess($_.DisplayName, 'remove LAN allow rule')) { Remove-NetFirewallRule -DisplayName $_.DisplayName }
  }
  Say 'revert done. Defender changes: run Tools\harden\harden-defender.ps1 -Revert'
  return
}

# ---------------------------------------------------------------- 1. firewall
Say '--- 1. Windows Firewall'
$profiles = Get-NetFirewallProfile
foreach ($p in $profiles) {
  if ($p.Enabled -eq $true) { Say "  $($p.Name): already enabled" ; continue }
  $target = 'enable'
  if ($Apply) {
    if ($PSCmdlet.ShouldProcess($p.Name, 'enable firewall profile, inbound default Block')) {
      Set-NetFirewallProfile -Profile $p.Name -Enabled True
      Set-NetFirewallProfile -Profile $p.Name -DefaultInboundAction Block -DefaultOutboundAction Allow
      Say "  $($p.Name): ENABLED (inbound Block, outbound Allow)"
    }
  } else { Say "  [plan] $($p.Name): enable (inbound Block, outbound Allow)" }
}

Say '--- 1b. LAN allow rules (Private profile only)'
foreach ($app in $lanApps) {
  $rule = Get-LanRuleName $app
  $existing = Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue
  if ($existing) { Say "  [ok] $($app.Name)"; continue }
  if ($app.Exe -and -not (Test-Path $app.Exe)) { Say "  [skip] $($app.Name): executable not present"; continue }
  if ($Apply) {
    # One rule per port: a comma-joined LocalPort string was rejected by
    # New-NetFirewallRule on this box ("the port is invalid"), and per-port rules
    # make the resulting scope unambiguous either way.
    $legacy = Get-NetFirewallRule -DisplayName ("DSH LAN allow - {0}" -f $app.Name) -ErrorAction SilentlyContinue
    foreach ($portSpec in $app.Ports) {
      $ruleName = "DSH LAN allow - $($app.Name) $portSpec"
      if ($legacy -or (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
        Say "  [ok] $($app.Name) port $portSpec"; continue
      }
      if ($PSCmdlet.ShouldProcess($ruleName, 'create inbound allow on Private profile')) {
        $params = @{
          DisplayName = $ruleName; Direction = 'Inbound'; Action = 'Allow'; Profile = 'Private'
          Protocol = 'TCP'; LocalPort = [string]$portSpec
          Description = 'Kept reachable on trusted networks only; the public profile stays closed.'
        }
        if ($app.Exe) { $params.Program = $app.Exe }
        try {
          New-NetFirewallRule @params | Out-Null
          Say "  [add] $($app.Name) port $portSpec (Private)"
        } catch {
          Say "  [FAIL] $($app.Name) port $portSpec : $($_.Exception.Message)"
        }
      }
    }
  } else { Say "  [plan] allow $($app.Name) ports $($app.Ports -join ',') on Private only" }
}
$smb = Get-NetFirewallRule -DisplayName 'DSH*' -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -match 'SMB|445' }
Say '  (no rule added for 135/445/5357 — closing those is the point)'

# ---------------------------------------------------------------- 2. defender
Say '--- 2. Microsoft Defender'
if ($SkipDefender) { Say '  skipped (-SkipDefender)' }
else {
  $hd = Join-Path $PSScriptRoot 'harden-defender.ps1'
  if (-not (Test-Path $hd)) { Say "  [skip] harden-defender.ps1 not found next to this script" }
  elseif ($Apply) {
    if ($PSCmdlet.ShouldProcess('Defender', 'apply the dev hardening baseline')) {
      & $hd -Apply -Profile dev -Confirm:$false
      Say '  Defender baseline applied (see its own backup under Tools\harden\.state)'
    }
  } else { Say '  [plan] run harden-defender.ps1 -Apply -Profile dev (see -Status output separately)' }
}

# ---------------------------------------------------------------- 3. wireguard
Say '--- 3. Proton VPN WireGuard service'
$wg = Get-CimInstance Win32_Service -Filter "Name='ProtonVPN WireGuard'"
if (-not $wg) { Say '  [skip] service not installed' }
else {
  Say "  current: $($wg.PathName)"
  $broken = $wg.PathName -match '\\v(\d+\.\d+\.\d+)\\'
  $curVer = if ($broken) { $Matches[1] } else { $null }
  $base = Join-Path $env:ProgramFiles 'Proton\VPN'
  $versions = Get-ChildItem $base -Directory -ErrorAction SilentlyContinue |
              Where-Object { $_.Name -match '^v\d+\.\d+\.\d+$' } |
              Sort-Object { [version]($_.Name.TrimStart('v')) } -Descending
  $target = $versions | Where-Object {
    (Test-Path (Join-Path $_.FullName 'ProtonVPN.WireGuardService.exe'))
  } | Select-Object -First 1
  if (-not $target) { Say '  [skip] no version folder with ProtonVPN.WireGuardService.exe' }
  elseif ($target.Name -eq "v$curVer") { Say "  [ok] already points at $($target.Name)" }
  else {
    $exe = Join-Path $target.FullName 'ProtonVPN.WireGuardService.exe'
    $cfgDir = Join-Path $target.FullName 'ServiceData\WireGuard'
    $cfg = Join-Path $cfgDir 'ProtonVPN.conf'
    Say "  [plan] repoint to $exe and $cfg (was v$curVer)"
    if ($Apply) {
      if ($PSCmdlet.ShouldProcess('ProtonVPN WireGuard', "repoint to $($target.Name)")) {
        New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
        $binPath = '"{0}" "{1}" tls' -f $exe, $cfg
        # sc.exe parses its own command line, so a quoted binPath goes through three
        # layers of quoting and failed with 1639 (ERROR_INVALID_COMMAND_LINE). The
        # service CIM Change method takes the string as data - no quoting at all.
        $svc = Get-CimInstance Win32_Service -Filter "Name='ProtonVPN WireGuard'"
        $res = Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{ PathName = $binPath }
        if ($res.ReturnValue -ne 0) { throw "service Change returned $($res.ReturnValue)" }
        $after = (Get-CimInstance Win32_Service -Filter "Name='ProtonVPN WireGuard'").PathName
        Say "  new: $after"
        Start-Service 'ProtonVPN WireGuard' -ErrorAction SilentlyContinue
        Get-Service 'ProtonVPN WireGuard' | ForEach-Object { Say "  service state: $($_.Status)" }
      }
    }
  }
}

# ---------------------------------------------------------------- summary
Say '--- verification'
$rows = @()
foreach ($p in (Get-NetFirewallProfile)) { $rows += [pscustomobject]@{ Item = "firewall:$($p.Name)"; Value = $p.Enabled } }
$mp = Get-MpPreference
if ($isAdmin) {
  $rows += [pscustomobject]@{ Item = 'PUAProtection'; Value = $mp.PUAProtection }
  $rows += [pscustomobject]@{ Item = 'MAPSReporting'; Value = $mp.MAPSReporting }
  $rows += [pscustomobject]@{ Item = 'NetworkProtection'; Value = $mp.EnableNetworkProtection }
  $rows += [pscustomobject]@{ Item = 'ControlledFolderAccess'; Value = $mp.EnableControlledFolderAccess }
  $rows += [pscustomobject]@{ Item = 'ASR rules configured'; Value = @($mp.AttackSurfaceReductionRules_Ids).Count }
}
$wg2 = Get-CimInstance Win32_Service -Filter "Name='ProtonVPN WireGuard'"
$rows += [pscustomobject]@{ Item = 'WireGuard service'; Value = $wg2.PathName }
$rows | Format-Table -AutoSize | Out-String | Write-Host

$resultFile = Join-Path $StateDir "finalize-security-$TS.result.json"
@{ mode = $(if($Apply){'apply'}else{'preview'}); elevated = $isAdmin; log = $log; rows = $rows } |
  ConvertTo-Json -Depth 4 | Set-Content $resultFile -Encoding UTF8
Say "result: $resultFile"
Say 'done'


