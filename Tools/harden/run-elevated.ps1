# Elevated wrapper: proves whether elevation happened, then runs the fix and captures
# every line of output and the terminating error into one file.
$ErrorActionPreference = 'Continue'
$here = $PSScriptRoot
$stamp = Get-Date -Format 'yyyyMMddTHHmmss'
$out = Join-Path $here ".state\elevated-run-$stamp.log"
New-Item -ItemType Directory -Force -Path (Join-Path $here '.state') | Out-Null

$who = [Security.Principal.WindowsIdentity]::GetCurrent()
$admin = ([Security.Principal.WindowsPrincipal]$who).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
"probe: time=$stamp user=$($who.Name) admin=$admin pwd=$($PWD.Path)" | Out-File -FilePath $out -Encoding utf8
"probe copy: $(Join-Path $here 'elevation-probe.txt')" | Out-File -FilePath (Join-Path $here 'elevation-probe.txt') -Encoding utf8 -Append

if (-not $admin) {
    "NOT ELEVATED - aborting" | Out-File -FilePath $out -Append -Encoding utf8
    exit 2
}

try {
    & (Join-Path $here 'FINALIZE-SECURITY.ps1') -Apply *>&1 |
        Tee-Object -FilePath $out -Append | Out-Host
    "exit=$LASTEXITCODE" | Out-File -FilePath $out -Append -Encoding utf8
    exit $LASTEXITCODE
}
catch {
    "EXCEPTION: $($_.Exception.GetType().Name): $($_.Exception.Message)" | Out-File -FilePath $out -Append -Encoding utf8
    "AT: $($_.InvocationInfo.PositionMessage)" | Out-File -FilePath $out -Append -Encoding utf8
    exit 1
}
