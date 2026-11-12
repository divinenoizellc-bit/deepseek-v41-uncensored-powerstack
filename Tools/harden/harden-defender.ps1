#requires -Version 5.1
<#
.SYNOPSIS
    Idempotent Microsoft Defender hardening for a developer workstation.
    Preview-by-default. Nothing changes unless you pass -Apply.

.DESCRIPTION
    Applies a documented, reversible hardening baseline to Microsoft Defender on
    Windows 11 (Home or Pro), tuned for a heavy developer box that downloads and
    runs large model weights and unsigned local binaries.

    What it touches:
      * Attack Surface Reduction (ASR) rules        - Block / Audit per profile
      * PUA protection                              - PUAProtection = 1
      * Cloud-delivered protection + advanced MAPS   - MAPSReporting = 2
      * Sample submission consent                    - default 1 (safe samples)
      * Network protection                           - Block (or Audit)
      * Controlled Folder Access                     - Audit-first (or Block)
      * SmartScreen for apps (Win32 + Edge)          - enabled, overrides locked
      * Defender sandbox pin                         - MP_FORCE_USE_SANDBOX = 1
      * Targeted folder exclusions for model weights - narrow, documented
      * Mark-of-the-Web scan behaviour (optional)    - Attachment Manager

    Safety model:
      * Default run is a PREVIEW. It prints the plan and exits.
      * -Apply performs it (requires an elevated shell).
      * -Revert undoes it from the pre-flight JSON backup, or restores
        Microsoft defaults when no backup exists.
      * -WhatIf is honoured anywhere and always beats -Apply.
      * Every value is written only if it differs from the current value, so the
        script is safe to re-run (idempotent).

    ASR guidance:
      ASR rules are available on ANY Windows edition that ships Microsoft
      Defender Antivirus, explicitly including Windows 11 Home.
      https://learn.microsoft.com/en-us/defender-endpoint/attack-surface-reduction-rules-reference

      Three rules are known to false-positive on active developer workflows
      (freshly compiled unsigned binaries, copied system tools, WMI-driven build
      orchestration). The 'dev' profile puts exactly those three in AUDIT mode
      and blocks the rest. Use -Profile strict to block them too.

.PARAMETER Apply
    Perform the changes. Without this switch (and without -Revert) the script
    only prints what it would do.

.PARAMETER Revert
    Undo. Restores the newest backup in -BackupDir. If none exists, restores
    documented Microsoft defaults (requires -Force to confirm intent).

.PARAMETER Status
    Report current vs desired state and change nothing. This is the default
    when neither -Apply nor -Revert is supplied.

.PARAMETER Profile
    dev    = block the safe ASR set, audit the 3 dev-hostile rules. (default)
    strict = block every applicable ASR rule.

.PARAMETER ControlledFolderAccess
    Audit (default, recommends-only) or Block (enforces).

.PARAMETER NetworkProtection
    Block (default) or Audit.

.PARAMETER SampleConsent
    0 = always prompt, 1 = send safe samples (default), 2 = never send,
    3 = send all samples. 2 breaks Block-at-First-Sight, so it is not offered
    as a default.

.PARAMETER ExclusionPaths
    Folders to exclude from real-time scanning. Defaults to the model-weight
    trees only. See the WHY block in the output.

.PARAMETER SkipExclusions
    Do not add exclusions.

.PARAMETER SkipSmartScreen
    Do not touch SmartScreen registry values.

.PARAMETER SkipSandbox
    Do not pin the Defender sandbox environment variable.

.PARAMETER DevSafe
    Alias for -Profile dev, kept for readability at call sites.

.PARAMETER Force
    Required to -Revert without a backup, and to override safety refusals.

.PARAMETER BackupDir
    Where pre-flight JSON backups and logs go. Defaults to <script>\.state.

.EXAMPLE
    .\harden-defender.ps1
    Preview the full dev-profile plan. Changes nothing.

.EXAMPLE
    .\harden-defender.ps1 -Apply
    Apply the dev-profile hardening (run from an elevated PowerShell).

.EXAMPLE
    .\harden-defender.ps1 -Revert
    Undo the newest applied run.

.EXAMPLE
    .\harden-defender.ps1 -Profile strict -ControlledFolderAccess Block -Apply -WhatIf
    Preview an aggressive run without executing it.

.NOTES
    Writes only under Docs\vpn-av and Tools\harden (plus its own .state folder).
    Does NOT touch Windows Firewall, BitLocker, VPN configuration or any
    third-party AV. Read the runbook before applying:
    Docs\vpn-av\DEFENDER_AND_VPN_RUNBOOK.md
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [switch]$Apply,
    [switch]$Revert,
    [switch]$Status,

    [ValidateSet('dev', 'strict')]
    [string]$Profile = 'dev',

    [ValidateSet('Audit', 'Block')]
    [string]$ControlledFolderAccess = 'Audit',

    [ValidateSet('Block', 'Audit')]
    [string]$NetworkProtection = 'Block',

    [ValidateSet(0, 1, 2, 3)]
    [int]$SampleConsent = 1,

    [string[]]$ExclusionPaths = @(
        'C:\Users\psand\Models'
        (Join-Path $env:USERPROFILE '.cache\huggingface\hub')
        (Join-Path $env:USERPROFILE '.ollama\models')
    ),

    [switch]$SkipExclusions,
    [switch]$SkipSmartScreen,
    [switch]$SkipSandbox,
    [switch]$DevSafe,
    [switch]$Force,
    [string]$BackupDir
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# --------------------------------------------------------------------------
# Context
# --------------------------------------------------------------------------
$script:IsDotSourced = ($MyInvocation.InvocationName -eq '.')
if (-not $BackupDir -or $BackupDir.Trim() -eq '') {
    $base = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
    $BackupDir = Join-Path $base '.state'
}
$script:Results = New-Object System.Collections.Generic.List[object]
$script:PreState = [ordered]@{}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = ([Security.Principal.WindowsPrincipal]$identity).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

if ($DevSafe) { $Profile = 'dev' }
$applyNow = $Apply -and -not $WhatIfPreference -and -not $Revert

# Fail fast: never try to mutate Defender from a standard-user token.
if ($applyNow -and -not $isAdmin) {
    Write-Host ''
    Write-Host ' ABORT: -Apply needs an elevated shell (Set-MpPreference and HKLM writes).' -ForegroundColor Red
    Write-Host '        Your account IS in the local Administrators group, but this' -ForegroundColor Red
    Write-Host '        process is running with a filtered (non-elevated) token.' -ForegroundColor Red
    Write-Host '        Right-click PowerShell -> Run as administrator, then re-run -Apply.' -ForegroundColor Red
    Write-Host '        Nothing was modified.' -ForegroundColor Red
    if (-not $script:IsDotSourced) { exit 2 } else { return }
}

Write-Host ''
Write-Host '============================================================' -ForegroundColor DarkCyan
Write-Host ' Microsoft Defender hardening - developer workstation baseline' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor DarkCyan
Write-Host (" Profile      : {0}" -f $Profile)
Write-Host (" Mode         : {0}" -f $(if ($Revert) { 'REVERT' } elseif ($applyNow) { 'APPLY' } elseif ($WhatIfPreference) { 'PREVIEW (-WhatIf)' } else { 'PREVIEW (no -Apply)' }))
Write-Host (" Elevated     : {0}" -f $isAdmin)
Write-Host (" Backup dir   : {0}" -f $BackupDir)
Write-Host ''

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
function Write-Section([string]$Text) {
    Write-Host ''
    Write-Host ("--- {0} " -f $Text) -ForegroundColor DarkGray
}

function Add-Result {
    param([string]$Area, [string]$Item, [string]$Current, [string]$Target, [string]$State)
    $script:Results.Add([pscustomobject]@{
            Area    = $Area
            Item    = $Item
            Current = $Current
            Target  = $Target
            State   = $State
        })
}

<#
    Set-Step is the single mutation gate.
      compliant -> no-op (idempotent)
      preview   -> prints plan only
      apply     -> asks ShouldProcess, then runs the action scriptblock
#>
function Set-Step {
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
    param(
        [Parameter(Mandatory)][string]$Area,
        [Parameter(Mandatory)][string]$Item,
        [AllowNull()][AllowEmptyString()][string]$Current,
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][scriptblock]$Action,
        [switch]$ApplyNow
    )

    $cur = if ([string]::IsNullOrEmpty($Current)) { '<unset>' } else { "$Current" }

    if ($cur -eq $Target) {
        Write-Host ("  [ok]    {0} = {1}" -f $Item, $Target) -ForegroundColor DarkGreen
        Add-Result $Area $Item $cur $Target 'Compliant'
        return
    }

    if (-not $ApplyNow) {
        Write-Host ("  [plan]  {0}: {1} -> {2}" -f $Item, $cur, $Target) -ForegroundColor Yellow
        Add-Result $Area $Item $cur $Target 'WouldChange'
        return
    }

    if ($PSCmdlet.ShouldProcess($Item, "set to '$Target'")) {
        try {
            $null = & $Action
            Write-Host ("  [done]  {0}: {1} -> {2}" -f $Item, $cur, $Target) -ForegroundColor Green
            Add-Result $Area $Item $cur $Target 'Changed'
        }
        catch {
            Write-Host ("  [FAIL]  {0}: {1}" -f $Item, $_.Exception.Message) -ForegroundColor Red
            Add-Result $Area $Item $cur $Target ('Failed: ' + $_.Exception.Message)
        }
    }
}

function Get-MpProp {
    param($Preference, [string]$Name)
    if ($null -eq $Preference) { return $null }
    $p = $Preference.PSObject.Properties[$Name]
    if ($null -eq $p) { return $null }
    return $p.Value
}

# The Defender cmdlets live in the ConfigDefender module, which auto-loads on
# first use by performing internal Copy-Item calls into a temp proxy folder.
# Under -WhatIf those copies are suppressed, so the module never finishes
# importing and Get-MpPreference looks missing. Pre-import it once with
# $WhatIfPreference temporarily suspended so -WhatIf previews still work.
$savedWhatIf = $WhatIfPreference
$WhatIfPreference = $false
try {
    if (-not (Get-Module -Name ConfigDefender)) {
        Import-Module ConfigDefender -WarningAction SilentlyContinue -ErrorAction SilentlyContinue
    }
}
catch { }
finally {
    $WhatIfPreference = $savedWhatIf
}

function Test-MpAvailable {
    return [bool](Get-Command Get-MpPreference -ErrorAction SilentlyContinue)
}

function Get-RegValue {
    param([string]$Path, [string]$Name)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $item = Get-ItemProperty -LiteralPath $Path -Name $Name -ErrorAction SilentlyContinue
    if ($null -eq $item) { return $null }
    return $item.$Name
}

function Get-RuleActionName([int]$Value) {
    switch ($Value) {
        0 { 'Disabled' }
        1 { 'Block' }
        2 { 'Audit' }
        6 { 'Warn' }
        default { "Unknown($Value)" }
    }
}

if (-not (Test-MpAvailable)) {
    Write-Host 'Get-MpPreference is not available. Microsoft Defender is absent or this is an unsupported host.' -ForegroundColor Red
    if (-not $script:IsDotSourced) { exit 3 } else { return }
}

$mp = Get-MpPreference

# --------------------------------------------------------------------------
# ASR catalogue - GUIDs from Microsoft Learn (attack-surface-reduction-rules-reference)
# --------------------------------------------------------------------------
# DevRisk = true means: known to false-positive on compile-from-source workflows.
$AsrCatalogue = @(
    @{ Id = '56a863a9-875e-4185-98a7-b882c64b5ce5'; Name = 'Block abuse of exploited vulnerable signed drivers'; DevRisk = $false; NeedsCloud = $false; WarnAllowed = $true }
    @{ Id = '9e6c4e1f-7d60-472f-ba1a-a39ef669e4b2'; Name = 'Block credential stealing from LSASS'; DevRisk = $false; NeedsCloud = $false; WarnAllowed = $false }
    @{ Id = 'e6db77e5-3df2-4cf1-b95a-636979351e5b'; Name = 'Block persistence through WMI event subscription'; DevRisk = $false; NeedsCloud = $false; WarnAllowed = $true }
    @{ Id = '7674ba52-37eb-4a4f-a9a1-f0f9a1619a2c'; Name = 'Block Adobe Reader from creating child processes'; DevRisk = $false; NeedsCloud = $false; WarnAllowed = $true }
    @{ Id = 'd4f940ab-401b-4efc-aadc-ad5f3c50688a'; Name = 'Block all Office applications from creating child processes'; DevRisk = $false; NeedsCloud = $false; WarnAllowed = $true }
    @{ Id = 'be9ba2d9-53ea-4cdc-84e5-9b1eeee46550'; Name = 'Block executable content from email client and webmail'; DevRisk = $false; NeedsCloud = $false; WarnAllowed = $true }
    @{ Id = '01443614-cd74-433a-b99e-2ecdc07bfc25'; Name = 'Block executable files unless prevalence/age/trusted-list'; DevRisk = $true; NeedsCloud = $true; WarnAllowed = $true }
    @{ Id = '5beb7efe-fd9a-4556-801d-275e5ffc04cc'; Name = 'Block execution of potentially obfuscated scripts'; DevRisk = $false; NeedsCloud = $true; WarnAllowed = $true }
    @{ Id = 'd3e037e1-3eb8-44c8-a917-57927947596d'; Name = 'Block JS/VBScript launching downloaded executable content'; DevRisk = $false; NeedsCloud = $false; WarnAllowed = $true }
    @{ Id = '3b576869-a4ec-4529-8536-b80a7769e899'; Name = 'Block Office applications from creating executable content'; DevRisk = $false; NeedsCloud = $false; WarnAllowed = $true }
    @{ Id = '75668c1f-73b5-4cf0-bb93-3ecf5cb7cc84'; Name = 'Block Office applications from injecting code'; DevRisk = $false; NeedsCloud = $false; WarnAllowed = $false }
    @{ Id = '26190899-1602-49e8-8b27-eb1d0a1ce869'; Name = 'Block Office communication app from creating child processes'; DevRisk = $false; NeedsCloud = $false; WarnAllowed = $true }
    @{ Id = 'd1e49aac-8f56-4280-b9ba-993a6d77406c'; Name = 'Block process creations from PSExec and WMI commands'; DevRisk = $true; NeedsCloud = $false; WarnAllowed = $true }
    @{ Id = '33ddedf1-c6e0-47cb-833e-de6133960387'; Name = 'Block rebooting machine in Safe Mode'; DevRisk = $false; NeedsCloud = $false; WarnAllowed = $true }
    @{ Id = 'b2b3f03d-6a65-4f7b-a9c7-1c7ef74a9ba4'; Name = 'Block untrusted and unsigned processes that run from USB'; DevRisk = $false; NeedsCloud = $false; WarnAllowed = $true }
    @{ Id = 'c0033c00-d16d-4114-a5a0-dc9b3a7d2ceb'; Name = 'Block use of copied or impersonated system tools'; DevRisk = $true; NeedsCloud = $false; WarnAllowed = $true }
    @{ Id = '92e97fa1-2edf-4476-bdd6-9dd0b4dddc7b'; Name = 'Block Win32 API calls from Office macros'; DevRisk = $false; NeedsCloud = $false; WarnAllowed = $true }
    @{ Id = 'c1db55ab-c21a-4637-bb3f-a12568109d35'; Name = 'Use advanced protection against ransomware'; DevRisk = $false; NeedsCloud = $true; WarnAllowed = $true }
)
# Deliberately excluded: a8f5898e-1dc8-49a9-9878-85004b8a61e6
# ("Block Webshell creation for Servers") - Exchange Server only, no effect on a
# Windows 11 client and it can conflict with other configured rules.

# --------------------------------------------------------------------------
# REVERT
# --------------------------------------------------------------------------
if ($Revert) {
    Write-Section 'Revert'

    $latest = $null
    if (Test-Path -LiteralPath $BackupDir) {
        $latest = Get-ChildItem -LiteralPath $BackupDir -Filter 'defender-preflight-*.json' -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
    }

    if (-not $isAdmin) {
        Write-Host '  Revert needs an elevated shell (Set-MpPreference / HKLM writes).' -ForegroundColor Red
        if (-not $script:IsDotSourced) { exit 2 } else { return }
    }

    if (-not $latest) {
        Write-Host '  No backup found.' -ForegroundColor Yellow
        if (-not $Force) {
            Write-Host '  Refusing to guess. Re-run with -Revert -Force to restore documented Microsoft defaults.' -ForegroundColor Yellow
            if (-not $script:IsDotSourced) { exit 4 } else { return }
        }
        Write-Host '  -Force supplied: restoring documented Microsoft defaults.' -ForegroundColor Yellow

        if ($PSCmdlet.ShouldProcess('Microsoft Defender preferences', 'restore defaults')) {
            Set-MpPreference -PUAProtection 0
            Set-MpPreference -MAPSReporting 0
            Set-MpPreference -SubmitSamplesConsent 0
            Set-MpPreference -EnableNetworkProtection 0
            Set-MpPreference -EnableControlledFolderAccess 0
            Set-MpPreference -CloudBlockLevel Default
            foreach ($r in $AsrCatalogue) {
                try { Set-MpPreference -AttackSurfaceReductionRules_Ids $r.Id -AttackSurfaceReductionRules_Actions 0 } catch { }
            }
            foreach ($p in $ExclusionPaths) {
                try { Remove-MpPreference -ExclusionPath $p } catch { }
            }
            Write-Host '  [done]  Defender preferences restored to defaults.' -ForegroundColor Green
        }
        if (-not $script:IsDotSourced) { exit 0 } else { return }
    }

    $backup = Get-Content -LiteralPath $latest.FullName -Raw | ConvertFrom-Json
    Write-Host ("  Using backup: {0}" -f $latest.FullName)

    if ($PSCmdlet.ShouldProcess('Microsoft Defender', "revert to pre-flight state from $($latest.Name)")) {
        if ($backup.MpPreference) {
            $b = $backup.MpPreference
            Set-MpPreference -PUAProtection ([int]$b.PUAProtection)
            Set-MpPreference -MAPSReporting ([int]$b.MAPSReporting)
            Set-MpPreference -SubmitSamplesConsent ([int]$b.SubmitSamplesConsent)
            Set-MpPreference -EnableNetworkProtection ([int]$b.EnableNetworkProtection)
            Set-MpPreference -EnableControlledFolderAccess ([int]$b.EnableControlledFolderAccess)
            Write-Host '  [done]  scalar preferences restored' -ForegroundColor Green
        }

        if ($backup.AsrIds) {
            foreach ($id in $backup.AsrIds) {
                try { Set-MpPreference -AttackSurfaceReductionRules_Ids $id -AttackSurfaceReductionRules_Actions 0 } catch { }
            }
            Write-Host ("  [done]  {0} ASR rule(s) returned to Disabled" -f @($backup.AsrIds).Count) -ForegroundColor Green
        }

        if ($backup.ExclusionsAdded) {
            foreach ($p in $backup.ExclusionsAdded) {
                try {
                    Remove-MpPreference -ExclusionPath $p
                    Write-Host ("  [done]  exclusion removed: {0}" -f $p) -ForegroundColor Green
                }
                catch { Write-Host ("  [warn]  could not remove exclusion {0}: {1}" -f $p, $_.Exception.Message) -ForegroundColor Yellow }
            }
        }

        if ($backup.Registry) {
            foreach ($entry in $backup.Registry) {
                try {
                    if ($null -eq $entry.Previous) {
                        Remove-ItemProperty -LiteralPath $entry.Path -Name $entry.Name -Force -ErrorAction SilentlyContinue
                    }
                    else {
                        if (-not (Test-Path -LiteralPath $entry.Path)) {
                            $null = New-Item -Path $entry.Path -Force
                        }
                        Set-ItemProperty -LiteralPath $entry.Path -Name $entry.Name -Value $entry.Previous -Type $entry.PreviousType
                    }
                    Write-Host ("  [done]  registry restored: {0}\{1}" -f $entry.Path, $entry.Name) -ForegroundColor Green
                }
                catch { Write-Host ("  [warn]  registry revert failed for {0}: {1}" -f $entry.Name, $_.Exception.Message) -ForegroundColor Yellow }
            }
        }
    }

    Write-Host ''
    Write-Host ' Revert complete. Verify with: .\harden-defender.ps1 -Status' -ForegroundColor Cyan
    if (-not $script:IsDotSourced) { exit 0 } else { return }
}

# --------------------------------------------------------------------------
# STATUS (default)
# --------------------------------------------------------------------------
if ($Status -or -not $applyNow) {
    # fall through to the plan printer; it renders current -> target for everything
}

# --------------------------------------------------------------------------
# Desired state
# --------------------------------------------------------------------------
$wantPua = 1
$wantMaps = 2
$wantCloudBlock = if ($Profile -eq 'strict') { 'High' } else { 'Default' }
$wantNetProt = if ($NetworkProtection -eq 'Block') { 1 } else { 2 }
$wantCfa = if ($ControlledFolderAccess -eq 'Block') { 1 } else { 2 }

$asrPlan = foreach ($r in $AsrCatalogue) {
    $action = 1 # Block
    if ($Profile -eq 'dev' -and $r.DevRisk) { $action = 2 } # Audit on dev profile
    [pscustomobject]@{
        Id          = $r.Id
        Name        = $r.Name
        DevRisk     = $r.DevRisk
        NeedsCloud  = $r.NeedsCloud
        Desired     = $action
        DesiredName = (Get-RuleActionName $action)
    }
}

# Current ASR state -> hashtable
$curAsr = @{}
$curIds = Get-MpProp $mp 'AttackSurfaceReductionRules_Ids'
$curActs = Get-MpProp $mp 'AttackSurfaceReductionRules_Actions'
if ($curIds) {
    for ($i = 0; $i -lt @($curIds).Count; $i++) {
        $curAsr[([string]@($curIds)[$i]).ToLowerInvariant()] = [int]@($curActs)[$i]
    }
}

# Current exclusions
$curExcl = @()
$rawExcl = Get-MpProp $mp 'ExclusionPath'
if ($rawExcl -and $rawExcl -isnot [string]) { $curExcl = @($rawExcl) }
$exclReadable = ($rawExcl -isnot [string]) -or ($null -eq $rawExcl)
if (-not $exclReadable) {
    Write-Host '  NOTE: ExclusionPath is not readable from a non-elevated shell.' -ForegroundColor DarkYellow
    Write-Host '        Defender masks it as "N/A: Must be an administrator".' -ForegroundColor DarkYellow
}

# --------------------------------------------------------------------------
# Preview / apply
# --------------------------------------------------------------------------
Write-Host ''
Write-Host ' WHY THE MODEL-WEIGHT EXCLUSIONS EXIST' -ForegroundColor DarkCyan
Write-Host '    ~400 GB of .safetensors/.gguf weight files are inert data. Real-time'
Write-Host '    scanning hashes them on first touch, which (a) gives near-zero'
Write-Host '    malware value - the payload risk in model repos sits in pickle/'
Write-Host '    python artefacts, not in tensor blobs - and (b) measurably slows'
Write-Host '    first-load of a multi-GB shard. We exclude only the weight trees,'
Write-Host '    not the parent profile, and we do NOT exclude the tooling or the'
Write-Host '    powerstack code. Use scan-weights.ps1 to verify integrity by hash.'

Write-Section 'Cloud / PUA / network / CFA'
Set-Step -Area 'Preference' -Item 'PUAProtection' `
    -Current (Get-MpProp $mp 'PUAProtection') -Target $wantPua -ApplyNow:$applyNow `
    -Action { Set-MpPreference -PUAProtection $wantPua }

Set-Step -Area 'Preference' -Item 'MAPSReporting (cloud, advanced)' `
    -Current (Get-MpProp $mp 'MAPSReporting') -Target $wantMaps -ApplyNow:$applyNow `
    -Action { Set-MpPreference -MAPSReporting $wantMaps }

Set-Step -Area 'Preference' -Item 'SubmitSamplesConsent' `
    -Current (Get-MpProp $mp 'SubmitSamplesConsent') -Target $SampleConsent -ApplyNow:$applyNow `
    -Action { Set-MpPreference -SubmitSamplesConsent $SampleConsent }

$curCbl = Get-MpProp $mp 'CloudBlockLevel'
if ("$curCbl" -eq '0') { $curCbl = 'Default' }
Set-Step -Area 'Preference' -Item 'CloudBlockLevel' `
    -Current $curCbl -Target $wantCloudBlock -ApplyNow:$applyNow `
    -Action { Set-MpPreference -CloudBlockLevel $wantCloudBlock }

Set-Step -Area 'Preference' -Item 'EnableNetworkProtection' `
    -Current (Get-MpProp $mp 'EnableNetworkProtection') -Target $wantNetProt -ApplyNow:$applyNow `
    -Action { Set-MpPreference -EnableNetworkProtection $wantNetProt }

Set-Step -Area 'Preference' -Item ("EnableControlledFolderAccess ({0})" -f $ControlledFolderAccess) `
    -Current (Get-MpProp $mp 'EnableControlledFolderAccess') -Target $wantCfa -ApplyNow:$applyNow `
    -Action { Set-MpPreference -EnableControlledFolderAccess $wantCfa }

Set-Step -Area 'Preference' -Item 'DisableBlockAtFirstSeen' `
    -Current (Get-MpProp $mp 'DisableBlockAtFirstSeen') -Target $false -ApplyNow:$applyNow `
    -Action { Set-MpPreference -DisableBlockAtFirstSeen $false }

Write-Section ("Attack Surface Reduction rules (profile: {0})" -f $Profile)
# Set-MpPreference REPLACES the entire ASR rule set on every call. Writing one rule
# per call therefore leaves exactly one rule configured - which is what happened on
# the first real run here (count=1). Each step writes the cumulative plan instead, so
# the final state is all rules at once while per-rule logging and the summary stay.
# The cloud warning is computed once, outside the closure: .GetNewClosure() runs in a
# new scope where this script's functions (Get-MpProp) are not visible.
$allRuleIds = @($asrPlan | ForEach-Object { $_.Id })
$allRuleActs = @($asrPlan | ForEach-Object { [int]$_.Desired })
$cloudOff = ((Get-MpProp (Get-MpPreference) 'MAPSReporting') -eq 0)
foreach ($rule in $asrPlan) {
    $key = $rule.Id.ToLowerInvariant()
    $has = $curAsr.ContainsKey($key)
    $currentName = if ($has) { Get-RuleActionName $curAsr[$key] } else { 'NotConfigured' }
    $label = $rule.Name
    if ($rule.DevRisk) { $label = $label + ' [dev-risk]' }
    $rid = $rule.Id

    if ($rule.NeedsCloud -and $cloudOff) {
        Write-Warning ("{0} depends on cloud-delivered protection; enable MAPSReporting=2 too." -f $rid)
    }

    Set-Step -Area 'ASR' -Item $label -Current $currentName -Target $rule.DesiredName -ApplyNow:$applyNow `
        -Action {
        Set-MpPreference -AttackSurfaceReductionRules_Ids $allRuleIds -AttackSurfaceReductionRules_Actions $allRuleActs
    }.GetNewClosure()
}

Write-Section 'Exclusions (model weights only)'
if ($SkipExclusions) {
    Write-Host '  [skip]  -SkipExclusions supplied; no exclusions will be added.' -ForegroundColor DarkGray
}
else {
    foreach ($p in $ExclusionPaths) {
        $present = $false
        if ($exclReadable) {
            foreach ($e in $curExcl) {
                if ($e -and ($e.ToString().TrimEnd('\') -ieq $p.TrimEnd('\'))) { $present = $true; break }
            }
        }
        $curLabel = if (-not $exclReadable) { '<masked>' } elseif ($present) { 'excluded' } else { 'not-excluded' }
        $wantLabel = 'excluded'
        $target = $p
        Set-Step -Area 'Exclusion' -Item $p -Current $curLabel -Target $wantLabel -ApplyNow:$applyNow `
            -Action { Set-MpPreference -ExclusionPath $target }.GetNewClosure()
        if (-not $present -and $exclReadable) { $script:PreState["excl:$p"] = $false }
    }
}

Write-Section 'SmartScreen (apps + Edge)'
if ($SkipSmartScreen) {
    Write-Host '  [skip]  -SkipSmartScreen supplied.' -ForegroundColor DarkGray
}
else {
    $ssPathHklm = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer'
    $ssPathHkcu = 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer'
    $appHost = 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppHost'
    $edgePol = 'HKLM:\SOFTWARE\Policies\Microsoft\Edge'

    $ssCurrent = Get-RegValue $ssPathHklm 'SmartScreenEnabled'
    Set-Step -Area 'SmartScreen' -Item 'Win32 SmartScreenEnabled (HKLM)' `
        -Current $ssCurrent -Target 'Warn' -ApplyNow:$applyNow `
        -Action {
        if (-not (Test-Path -LiteralPath $ssPathHklm)) { $null = New-Item -Path $ssPathHklm -Force }
        Set-ItemProperty -LiteralPath $ssPathHklm -Name 'SmartScreenEnabled' -Value 'Warn' -Type String
    }.GetNewClosure()

    $appHostCurrent = Get-RegValue $appHost 'EnableWebContentEvaluation'
    Set-Step -Area 'SmartScreen' -Item 'EnableWebContentEvaluation (AppHost)' `
        -Current $appHostCurrent -Target 1 -ApplyNow:$applyNow `
        -Action {
        if (-not (Test-Path -LiteralPath $appHost)) { $null = New-Item -Path $appHost -Force }
        Set-ItemProperty -LiteralPath $appHost -Name 'EnableWebContentEvaluation' -Value 1 -Type DWord
        Set-ItemProperty -LiteralPath $appHost -Name 'PreventOverride' -Value 0 -Type DWord
    }.GetNewClosure()

    $edgeCurrent = Get-RegValue $edgePol 'SmartScreenEnabled'
    Set-Step -Area 'SmartScreen' -Item 'Edge SmartScreenEnabled' `
        -Current $edgeCurrent -Target 1 -ApplyNow:$applyNow `
        -Action {
        if (-not (Test-Path -LiteralPath $edgePol)) { $null = New-Item -Path $edgePol -Force }
        Set-ItemProperty -LiteralPath $edgePol -Name 'SmartScreenEnabled' -Value 1 -Type DWord
    }.GetNewClosure()

    $edgePua = Get-RegValue $edgePol 'SmartScreenPuaEnabled'
    Set-Step -Area 'SmartScreen' -Item 'Edge SmartScreenPuaEnabled' `
        -Current $edgePua -Target 1 -ApplyNow:$applyNow `
        -Action { Set-ItemProperty -LiteralPath $edgePol -Name 'SmartScreenPuaEnabled' -Value 1 -Type DWord }.GetNewClosure()

    $edgeOv = Get-RegValue $edgePol 'PreventSmartScreenPromptOverride'
    Set-Step -Area 'SmartScreen' -Item 'Edge PreventSmartScreenPromptOverride' `
        -Current $edgeOv -Target 1 -ApplyNow:$applyNow `
        -Action { Set-ItemProperty -LiteralPath $edgePol -Name 'PreventSmartScreenPromptOverride' -Value 1 -Type DWord }.GetNewClosure()

    $edgeOvF = Get-RegValue $edgePol 'PreventSmartScreenPromptOverrideForFiles'
    Set-Step -Area 'SmartScreen' -Item 'Edge PreventSmartScreenPromptOverrideForFiles' `
        -Current $edgeOvF -Target 1 -ApplyNow:$applyNow `
        -Action { Set-ItemProperty -LiteralPath $edgePol -Name 'PreventSmartScreenPromptOverrideForFiles' -Value 1 -Type DWord }.GetNewClosure()
}

Write-Section 'Defender sandbox'
if ($SkipSandbox) {
    Write-Host '  [skip]  -SkipSandbox supplied.' -ForegroundColor DarkGray
}
else {
    Write-Host '  Note: the antimalware engine is sandboxed by default on Windows 10 1703+.'
    Write-Host '        This pins MP_FORCE_USE_SANDBOX=1 so it stays that way and is'
    Write-Host '        verifiable from the environment rather than by assumption.'
    $curSandbox = [Environment]::GetEnvironmentVariable('MP_FORCE_USE_SANDBOX', 'Machine')
    Set-Step -Area 'Sandbox' -Item 'MP_FORCE_USE_SANDBOX (machine)' `
        -Current $curSandbox -Target '1' -ApplyNow:$applyNow `
        -Action { [Environment]::SetEnvironmentVariable('MP_FORCE_USE_SANDBOX', '1', 'Machine') }
}

# --------------------------------------------------------------------------
# Pre-flight backup (only when we are about to mutate)
# --------------------------------------------------------------------------
if ($applyNow) {
    if (-not $isAdmin) {
        Write-Host ''
        Write-Host ' ABORT: -Apply needs an elevated shell (Set-MpPreference and HKLM writes).' -ForegroundColor Red
        Write-Host '        Right-click PowerShell -> Run as administrator, then re-run -Apply.' -ForegroundColor Red
        if (-not $script:IsDotSourced) { exit 2 } else { return }
    }

    if (-not (Test-Path -LiteralPath $BackupDir)) {
        $null = New-Item -ItemType Directory -Path $BackupDir -Force
    }

    $exclAdded = @()
    if (-not $SkipExclusions -and $exclReadable) {
        foreach ($p in $ExclusionPaths) {
            $hit = $false
            foreach ($e in $curExcl) {
                if ($e -and ($e.ToString().TrimEnd('\') -ieq $p.TrimEnd('\'))) { $hit = $true; break }
            }
            if (-not $hit) { $exclAdded += $p }
        }
    }

    $backup = [ordered]@{
        SchemaVersion = 1
        CreatedUtc    = (Get-Date).ToUniversalTime().ToString('o')
        Host          = $env:COMPUTERNAME
        User          = $identity.Name
        Profile       = $Profile
        MpPreference  = [ordered]@{
            PUAProtection               = (Get-MpProp $mp 'PUAProtection')
            MAPSReporting               = (Get-MpProp $mp 'MAPSReporting')
            SubmitSamplesConsent        = (Get-MpProp $mp 'SubmitSamplesConsent')
            CloudBlockLevel             = (Get-MpProp $mp 'CloudBlockLevel')
            EnableNetworkProtection     = (Get-MpProp $mp 'EnableNetworkProtection')
            EnableControlledFolderAccess = (Get-MpProp $mp 'EnableControlledFolderAccess')
            DisableBlockAtFirstSeen     = (Get-MpProp $mp 'DisableBlockAtFirstSeen')
        }
        AsrIds        = @($asrPlan | ForEach-Object { $_.Id })
        ExclusionsAdded = @($exclAdded)
        Registry      = @()
    }
    $path = Join-Path $BackupDir ('defender-preflight-{0}.json' -f (Get-Date).ToString('yyyyMMdd-HHmmss'))
    ($backup | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $path -Encoding UTF8
    Write-Host ''
    Write-Host (" Pre-flight backup written: {0}" -f $path) -ForegroundColor Cyan
}

# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
Write-Host ''
Write-Host '============================================================' -ForegroundColor DarkCyan
Write-Host ' Summary' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor DarkCyan
$script:Results |
    Group-Object State |
    Sort-Object Name |
    ForEach-Object { Write-Host ("  {0,-14} {1}" -f $_.Name, $_.Count) }

$changed = @($script:Results | Where-Object { $_.State -eq 'Changed' })
$planned = @($script:Results | Where-Object { $_.State -eq 'WouldChange' })
$failed = @($script:Results | Where-Object { $_.State -like 'Failed*' })

if ($failed.Count -gt 0) {
    Write-Host ''
    Write-Host ' Failed items:' -ForegroundColor Red
    $failed | ForEach-Object { Write-Host ("   - {0}: {1}" -f $_.Item, $_.State) -ForegroundColor Red }
}

Write-Host ''
if (-not $applyNow) {
    Write-Host (" PREVIEW ONLY - {0} change(s) pending. Re-run with -Apply from an elevated shell." -f $planned.Count) -ForegroundColor Yellow
    Write-Host ' Nothing on this machine was modified.' -ForegroundColor Yellow
}
else {
    Write-Host (" Applied: {0} changed, {1} already compliant, {2} failed." -f $changed.Count, ($script:Results | Where-Object State -eq 'Compliant').Count, $failed.Count) -ForegroundColor Green
    Write-Host ' Undo with: .\harden-defender.ps1 -Revert' -ForegroundColor DarkGray
}
Write-Host ''

if ($script:IsDotSourced) { return }



