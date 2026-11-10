<#
  publish.ps1 - publish this toolkit (never the weights) to GitHub and/or Hugging Face.

  Why never the weights: they are 352.5 GiB, MIT-licensed, and already hosted at pinned
  revisions by AtomicChat / ISTA-DASLab / Unsloth. This repo ships the pins, the audit and
  the launcher - the part that is actually ours - and points at theirs.

  Preconditions are checked, not assumed: `gh auth status` and `hf auth whoami` must both
  succeed for the target they are asked for. Nothing is pushed with an absent login.

  Usage:
    pwsh -File Tools/runtime/publish.ps1 -Target github -Repo deepseek-v41-uncensored-powerstack
    pwsh -File Tools/runtime/publish.ps1 -Target hf-dataset -Name deepseek-v41-uncensored-pins
    pwsh -File Tools/runtime/publish.ps1 -Target github -DryRun
#>
[CmdletBinding(SupportsShouldProcess)]
param(
  [ValidateSet('github', 'hf-dataset', 'both')]
  [string]$Target = 'github',
  [string]$Repo = 'deepseek-v41-uncensored-powerstack',
  [string]$Name = 'deepseek-v41-uncensored-pins',
  [string]$Visibility = 'public',
  [string]$ProjectRoot = '',
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
Push-Location $ProjectRoot
try {
  Write-Host 'DeepSeek-V4.1-Flash-1017 power stack :: publish' -ForegroundColor Cyan
  Write-Host "project: $ProjectRoot"

  # resolve the CLIs, they are not always on PATH in a fresh shell
  $gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
  if (-not $gh -and (Test-Path 'C:\Program Files\GitHub CLI\gh.exe')) { $gh = 'C:\Program Files\GitHub CLI\gh.exe' }
  $hf = (Get-Command hf -ErrorAction SilentlyContinue).Source
  if (-not $hf) { $hf = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\Scripts\hf.exe' }
  if (-not (Test-Path $hf)) { $hf = $null }

  # --- preflight -------------------------------------------------------------
  if (-not (Test-Path '.git')) { throw 'not a git repository: run this from the project root' }
  $dirty = git status --porcelain
  if ($dirty) {
    Write-Host '  working tree has uncommitted changes:' -ForegroundColor Yellow
    $dirty | Select-Object -First 10 | ForEach-Object { Write-Host "    $_" }
    Write-Host '  commit first: git add -A; git commit -m "..."'
  }
  $head = git rev-parse --short HEAD
  Write-Host "  HEAD: $head"

  foreach ($f in @('manifests/acceptance.json', 'Docs/security/SECURITY_AUDIT.md', 'README.md', 'LICENSE', 'NOTICE')) {
    if (-not (Test-Path $f)) { throw "required file missing: $f" }
  }
  # hard stop: no weight file may ever be committed
  $big = git ls-files | ForEach-Object { Get-Item $_ -ErrorAction SilentlyContinue } |
         Where-Object { $_ -and $_.Length -gt 50MB }
  if ($big) {
    $big | ForEach-Object { Write-Host ("  !! {0} MB {1}" -f [math]::Round($_.Length/1MB), $_.FullName) -ForegroundColor Red }
    throw 'a file larger than 50 MB is tracked; weights must never be committed'
  }
  Write-Host '  [ok] no weights tracked, required files present'

  # --- GitHub ----------------------------------------------------------------
  if ($Target -in @('github', 'both')) {
    Write-Host ''
    Write-Host 'GitHub:' -ForegroundColor Cyan
    $auth = (& $gh auth status 2>&1)
    if ($LASTEXITCODE -ne 0) {
      Write-Host '  not authenticated. Run: gh auth login' -ForegroundColor Yellow
      Write-Host '  then re-run this script.' -ForegroundColor Yellow
    } else {
      $owner = (& $gh api user --jq .login 2>$null)
      Write-Host "  authenticated as: $owner"
      $exists = (& $gh repo view "$owner/$Repo" --json name 2>$null)
      if ($DryRun) {
        Write-Host "  [dry-run] gh repo create $owner/$Repo --$Visibility --source . --push"
      } elseif (-not $exists) {
        if ($PSCmdlet.ShouldProcess("$owner/$Repo", 'create and push')) {
          & $gh repo create "$owner/$Repo" "--$Visibility" --source . --push --description 'Verified mirror + power launcher for AtomicChat DeepSeek-V4.1-Flash-1017 Uncensored (GGUF, 551B MoE)'
          if ($LASTEXITCODE -ne 0) { throw 'gh repo create failed' }
          git push --tags 2>$null
          Write-Host "  published: https://github.com/$owner/$Repo" -ForegroundColor Green
        }
      } else {
        if ($PSCmdlet.ShouldProcess("$owner/$Repo", 'push')) {
          git remote get-url origin 2>$null | Out-Null
          if ($LASTEXITCODE -ne 0) { git remote add origin "https://github.com/$owner/$Repo.git" }
          git push -u origin HEAD
          if ($LASTEXITCODE -ne 0) { throw 'git push failed' }
          Write-Host "  pushed: https://github.com/$owner/$Repo" -ForegroundColor Green
        }
      }
    }
  }

  # --- Hugging Face (pins + audit only, no weights) ---------------------------
  if ($Target -in @('hf-dataset', 'both')) {
    Write-Host ''
    Write-Host 'Hugging Face dataset (manifests + audit, no weights):' -ForegroundColor Cyan
    $who = (& $hf auth whoami 2>&1)
    if ($LASTEXITCODE -ne 0) {
      Write-Host '  not authenticated. Run: hf auth login' -ForegroundColor Yellow
    } else {
      $user = ($who | Select-Object -First 1) -replace '\s.*$', ''
      Write-Host "  authenticated as: $user"
      $stage = Join-Path $env:TEMP ("pins-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
      New-Item -ItemType Directory -Force -Path $stage | Out-Null
      Copy-Item 'README.md', 'LICENSE', 'NOTICE', 'manifests' -Destination $stage -Recurse -Force
      Copy-Item 'Docs\security' -Destination $stage -Recurse -Force
      Copy-Item 'Docs\library'  -Destination $stage -Recurse -Force
      if ($DryRun) {
        Write-Host "  [dry-run] hf upload $user/$Name $stage . --repo-type dataset"
      } elseif ($PSCmdlet.ShouldProcess("$user/$Name", 'upload pins + audit')) {
        & $hf upload "$user/$Name" $stage . --repo-type dataset --private $false 2>&1 |
          Select-Object -Last 3 | ForEach-Object { Write-Host "    $_" }
        if ($LASTEXITCODE -ne 0) { throw 'hf upload failed' }
        Write-Host "  published: https://huggingface.co/datasets/$user/$Name" -ForegroundColor Green
      }
      Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
  }

  Write-Host ''
  Write-Host 'done. Nothing was published if a precondition above is still yellow.' -ForegroundColor DarkGray
}
finally { Pop-Location }

