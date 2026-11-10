# Defender & VPN Runbook — `DESKTOP-OFS67IF`

**Applies to:** Windows 11 Home 25H2 (26200.9711) · **User:** `DESKTOP-OFS67IF\psand`
**Companions:** `..\..\Docs\vpn-av\RECOMMENDATION.md` · `..\..\Tools\harden\*.ps1`

> **Status of this machine right now: NOTHING HAS BEEN APPLIED.**
> Every step below is prepared and smoke-tested, but the hardening is still pending. The
> scripts default to preview and require `-Apply` from an elevated shell. This is deliberate —
> per the brief, no system security settings were changed in the session that wrote this.

---

## 0. Why an elevated shell is required (and why it isn't a bug)

`psand` **is** a member of the local `Administrators` group, but every process it launches runs with a
**filtered (non-elevated) token** because UAC is on (`EnableLUA=1`, `ConsentPromptBehaviorAdmin=5`).

Consequences you will hit:

| Symptom | Cause |
| --- | --- |
| `Get-MpPreference` shows `ExclusionPath : {N/A: Must be an administrator…}` | Defender masks exclusions from a standard token |
| `Get-BitLockerVolume` / `Win32_EncryptableVolume` → `Access denied` | non-elevated |
| `Get-Tpm`, `Confirm-SecureBootUEFI` → `Access denied` | non-elevated |
| `Set-MpPreference` fails | needs admin |
| `harden-defender.ps1 -Apply` exits 2 with "ABORT: -Apply needs an elevated shell" | **by design** |

Open **Windows Terminal / PowerShell → right-click → Run as administrator**, then `cd` to
`…\deepseek-v41-uncensored-powerstack\Tools\harden`.

A one-shot elevated launch without leaving your current shell:

```powershell
Start-Process pwsh -Verb RunAs -ArgumentList '-NoExit','-Command',
  "cd 'C:\Users\psand\Desktop\Harness Machine\deepseek-v41-uncensored-powerstack\Tools\harden'"
```

---

## 1. What the hardening script changes (the contract)

`harden-defender.ps1` touches **only** these things. It does **not** touch the firewall, BitLocker, VPN
configuration, third-party AV, drivers, or boot configuration.

| # | Control | Default target | Reversible |
| --- | --- | --- | --- |
| 1 | `PUAProtection` | `1` (block) | ✅ |
| 2 | `MAPSReporting` (cloud) | `2` (advanced) | ✅ |
| 3 | `SubmitSamplesConsent` | `1` (safe samples) | ✅ |
| 4 | `CloudBlockLevel` | `Default` (`High` under `-Profile strict`) | ✅ |
| 5 | `EnableNetworkProtection` | `1` (block) | ✅ |
| 6 | `EnableControlledFolderAccess` | `2` (audit-first) | ✅ |
| 7 | `DisableBlockAtFirstSeen` | `False` | ✅ |
| 8 | ASR rules | 18 rules; **15 Block + 3 Audit** in `dev`, all Block in `strict` | ✅ |
| 9 | Defender exclusions | 3 model-weight paths | ✅ |
| 10 | SmartScreen (Win32 + AppHost + Edge ×4) | enabled, overrides locked | ✅ |
| 11 | `MP_FORCE_USE_SANDBOX` | `1` (pin) | ✅ |

### The three dev-risk ASR rules (why `dev` audits instead of blocks)

These have documented false-positive behaviour against compile-from-source workflows. `-Profile dev`
(the default) puts them in **Audit**; `-Profile strict` blocks them.

| Rule | GUID | Why it bites developers |
| --- | --- | --- |
| Block executable files unless prevalence/age/trusted-list | `01443614-cd74-433a-b99e-2ecdc07bfc25` | Blocks **freshly compiled, unsigned** binaries — i.e. your own build output |
| Block process creations from PSExec and WMI | `d1e49aac-8f56-4280-b9ba-993a6d77406c` | Breaks WMI-driven build/CI orchestration |
| Block use of copied or impersonated system tools | `c0033c00-d16d-4114-a5a0-dc9b3a7d2ceb` | Trips on toolchains that copy system binaries (MSYS/Cygwin-style) |

All other 15 rules default to Block. Two of them (`9e6c4e1f…` LSASS, `75668c1f…` Office injection) **do not
support Warn mode** — audit mode is the only observation path. Three rules (`01443614…`, `5beb7efe…`,
`c1db55ab…`) require cloud protection to function, which is why MAPS is enabled in the same pass.

Deliberately **excluded**: `a8f5898e-1dc8-49a9-9878-85004b8a61e6` *Block Webshell creation for Servers* —
Exchange Server only, no effect on a Windows 11 client.

GUIDs and dependency notes: [Microsoft Learn ASR reference](https://learn.microsoft.com/en-us/defender-endpoint/attack-surface-reduction-rules-reference)
(updated 2026-09-09). ASR is available on **Windows 11 Home** — the same page states the rules are
"available on any edition of Windows that includes Microsoft Defender Antivirus (for example, Windows 11 Home)".

---

## 2. Part A — Defender hardening, step by step

### A0. Baseline (no admin needed)

```powershell
Get-MpComputerStatus | Select-Object AMProductVersion,AMEngineVersion,
  AntivirusSignatureVersion,AntivirusSignatureLastUpdated,RealTimeProtectionEnabled

Get-MpPreference | Select-Object PUAProtection,MAPSReporting,SubmitSamplesConsent,
  CloudBlockLevel,EnableNetworkProtection,EnableControlledFolderAccess,
  AttackSurfaceReductionRules_Ids,AttackSurfaceReductionRules_Actions
```

Expected today: `PUAProtection 0`, `MAPSReporting 0`, `EnableNetworkProtection 0`,
`EnableControlledFolderAccess 0`, ASR arrays **empty**. That is the "before" picture.

### A1. Preview (safe, no admin)

```powershell
.\harden-defender.ps1                     # same as -Status
.\harden-defender.ps1 -WhatIf              # ShouldProcess dry-run
.\harden-defender.ps1 -Profile strict -WhatIf
```

Expected on the measured baseline: **`33 change(s) pending`** for `-Profile dev` (2 already compliant:
`CloudBlockLevel=Default`, `DisableBlockAtFirstSeen=False`) and **34** for `-Profile strict`. You should also
see `Nothing on this machine was modified.` plus the WHY block explaining the model-weight exclusions.

### A2. Apply (elevated)

```powershell
.\harden-defender.ps1 -Apply
```

What happens, in order:

1. Writes a pre-flight JSON backup to `Tools\harden\.state\defender-preflight-<timestamp>.json`
   (scalar prefs + the ASR IDs + the exclusions it is about to add).
2. Applies each control, skipping anything already compliant (idempotent — safe to re-run).
3. Prints `Compliant / Changed / Failed` counts.

To be conservative on a first pass, audit-first CFA is already the default:

```powershell
.\harden-defender.ps1 -Apply                                  # CFA=Audit, NetworkProtection=Block
.\harden-defender.ps1 -Apply -ControlledFolderAccess Block     # enforce CFA
.\harden-defender.ps1 -Apply -NetworkProtection Audit          # observe-only network protection
```

Re-run with `-Apply` to escalate from Audit to Block once the event log is quiet.

### A3. Verify (elevated — this is the step that proves it worked)

```powershell
$mp = Get-MpPreference
[pscustomobject]@{
  PUA             = $mp.PUAProtection                      # expect 1
  MAPS            = $mp.MAPSReporting                      # expect 2
  Consent         = $mp.SubmitSamplesConsent               # expect 1
  CloudBlock      = $mp.CloudBlockLevel                    # expect Default
  NetProtection   = $mp.EnableNetworkProtection            # expect 1
  CFA             = $mp.EnableControlledFolderAccess        # expect 2 (audit) or 1 (block)
  ASRCount        = ($mp.AttackSurfaceReductionRules_Ids | Measure-Object).Count   # expect 18
  BAFSdisabled    = $mp.DisableBlockAtFirstSeen            # expect False
  Exclusions      = ($mp.ExclusionPath -join '; ')
} | Format-List
```

Per-rule audit:

```powershell
$ids = $mp.AttackSurfaceReductionRules_Ids
$acts = $mp.AttackSurfaceReductionRules_Actions
for ($i=0; $i -lt $ids.Count; $i++) {
  '{0}  {1}' -f $ids[$i], @{0='Disabled';1='BLOCK';2='AUDIT';6='Warn'}[[int]$acts[$i]]
}
```

Expect `18` lines, three of them `AUDIT` (`01443614…`, `d1e49aac…`, `c0033c00…`).

SmartScreen:

```powershell
Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer' -Name SmartScreenEnabled
Get-ItemProperty 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppHost'  -Name EnableWebContentEvaluation
Get-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Edge' -Name SmartScreenEnabled,SmartScreenPuaEnabled,PreventSmartScreenPromptOverride
```

Expect `Warn` / `1` / `1`,`1`,`1`.

Sandbox pin:

```powershell
[Environment]::GetEnvironmentVariable('MP_FORCE_USE_SANDBOX','Machine')   # expect 1
Get-Process MsMpSvc | Select-Object Name,Id,StartTime                     # engine running
```

### A4. Watch what the rules do (verified log path)

The log exists and is enabled on this host:
`Microsoft-Windows-Windows Defender/Operational` (2,909 records at time of writing).

```powershell
# Everything Defender has said recently
Get-WinEvent -LogName 'Microsoft-Windows-Windows Defender/Operational' -MaxEvents 100 |
  Select-Object TimeCreated,Id,LevelDisplayName,@{n='Msg';e={$_.Message.Substring(0,[Math]::Min(200,$_.Message.Length))}} |
  Format-Table -Wrap
```

```powershell
# Filter for a specific ASR rule GUID (do this per dev-risk rule after enabling)
$guid = '01443614-cd74-433a-b99e-2ecdc07bfc25'
Get-WinEvent -LogName 'Microsoft-Windows-Windows Defender/Operational' -MaxEvents 2000 |
  Where-Object { $_.Message -match $guid } |
  Select-Object TimeCreated,Id,Message |
  Format-List
```

> Note: this host currently shows **zero** ASR events, which is exactly what "0 rules configured" looks
> like (§1.2 of the recommendation). After `-Apply`, ASR traffic should appear here. I did not assert specific
> event-ID numbers in this runbook because I could not verify them against Microsoft documentation in this
> session — filter on the rule **GUID** in the message body instead, which is unambiguous.

Escalation rule: leave a `dev-risk` rule in Audit for **one week of normal work**. If nothing in the log
would have broken a build, promote it:

```powershell
Set-MpPreference -AttackSurfaceReductionRules_Ids '01443614-cd74-433a-b99e-2ecdc07bfc25' `
                 -AttackSurfaceReductionRules_Actions 1   # 1 = Block
```

### A5. Revert

```powershell
.\harden-defender.ps1 -Revert                 # elevated; restores newest backup
.\harden-defender.ps1 -Revert -Force          # no backup: restore Microsoft defaults
```

`-Revert` restores the scalar preferences, sets every ASR ID it applied back to `Disabled`, removes the
exclusions it added, and puts registry values back (deleting them if they did not exist before). It is
backed by the JSON, not by guesswork.

Surgical single-control rollback:

```powershell
Set-MpPreference -EnableControlledFolderAccess 0
Set-MpPreference -PUAProtection 0
Remove-MpPreference -ExclusionPath 'C:\Users\psand\Models'
Set-MpPreference -AttackSurfaceReductionRules_Ids '<guid>' -AttackSurfaceReductionRules_Actions 0
```

### A6. If the build breaks — per-rule triage

| Symptom | Likely rule | Fix |
| --- | --- | --- |
| Freshly compiled `.exe`/`.dll` won't run | `01443614…` | leave in Audit (dev profile default) |
| MSBuild / CI / WMI orchestration fails | `d1e49aac…` | leave in Audit |
| `link.exe`, `cl.exe`, MSYS tools blocked | `c0033c00…` | leave in Audit |
| Webpack/Vite bundle flagged as obfuscated | `5beb7efe…` | per-rule exclusion or Audit |
| Unreal Editor / plugin DLL blocked | `01443614…` | exclude the **build output** dir, not the whole drive |
| Local python HTTP server blocked | `01443614…` | add that dir to ASR exclusions |

**Prefer a narrow path exclusion over disabling a whole rule.** Never exclude `C:\`, and never exclude a
directory that contains downloaded code.

---

## 3. Part B — Exclusions: the rationale, and how to audit them

### What we add and why

| Path | Why |
| --- | --- |
| `C:\Users\psand\Models` | tensor blobs you produced/downloaded and verified by hash |
| `C:\Users\psand\.cache\huggingface\hub` | HF weight cache |
| `C:\Users\psand\.ollama\models` | Ollama blob store |

**The honest argument:** ~400 GB of `.safetensors`/`.gguf` weights are inert data — they are not executable
by the runtime, and the real payload risk in a model repo sits in **pickle/Python artefacts**, not in tensor
blobs. Scanning them on every first touch costs real I/O and slows first load of a multi-GB shard for
near-zero detection value. Meanwhile **excluding a directory that contains code is how ransomware survives**
— Defender exclusions are a documented attacker technique. So: exclude the weight trees, and **nothing
else**. Do not exclude the tooling, the powerstack repo, `Tools\`, or your source directories.

This is a deliberate tradeoff, not a free win. It is mitigated by `scan-weights.ps1` (hash-integrity) rather
than by AV.

### Audit the list (elevated — this is the only way to see it)

```powershell
(Get-MpPreference).ExclusionPath
(Get-MpPreference).ExclusionExtension
(Get-MpPreference).ExclusionProcess
(Get-MpPreference).ExclusionIpAddress
```

Also check for policy-injected exclusions, which override everything:

```powershell
Get-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows Defender\Exclusions\Paths' -ErrorAction SilentlyContinue
```

**Rule: if you don't recognise an exclusion, remove it.** An unknown exclusion in `%TEMP%`, `%APPDATA%`, or a
user-writable path is a red flag.

### Bonus: Ollama blobs are self-verifying

Ollama names each blob `sha256-<64 hex>`, i.e. **the filename is the expected digest**. `scan-weights.ps1`
detects this and verifies content against the name with no manifest bookkeeping. Verified on this host:

```
Found 75 candidate file(s)
OkSelfAddressed  68      <- all matched their embedded SHA256
HashMismatch      0
```

That is a genuinely free tamper check you can run any time:

```powershell
.\scan-weights.ps1 -Root "$env:USERPROFILE\.ollama\models" -Verify -MaxBytes 52428800
```

---

## 4. Part C — Windows Firewall (NOT done by the script; do this separately)

**Current state: OFF on Domain, Private and Public** (verified three ways). This is the highest-severity
finding on the box. But enabling it is *not* a safe one-liner here: there are **760 rules, 518 enabled,
427 inbound-Allow**, all currently inert. Turning the firewall on activates all 427 at once.

Do it supervised:

1. **Inventory what must stay reachable** — from the listening-port scan: UnrealEditor `1985`,
   UnrealTraceServer `1981/1989`, python `8686`, zenserver `8558`, tradelocker `55446`, p4s `1666`.
2. **Prefer binding to loopback** over opening a port. Most dev servers accept `--host 127.0.0.1`.
3. Turn on the firewall **Public profile first** (least breakage, biggest win), then Private.
4. Verify your dev servers still work after each profile.

```powershell
# Preview: what inbound-allow rules exist and are enabled
Get-NetFirewallRule -Direction Inbound -Action Allow -Enabled True |
  Select-Object DisplayName,Profile | Sort-Object DisplayName

# Enable Public only (elevated)
Set-NetFirewallProfile -Profile Public -Enabled True

# Then Private, after confirming nothing broke
Set-NetFirewallProfile -Profile Private -Enabled True

# Back out instantly if needed
Set-NetFirewallProfile -Profile Public,Private -Enabled False
```

**Also do, independent of the firewall** (elevated):

```powershell
# SMB is listening on all interfaces with signing and encryption OFF
Set-SmbServerConfiguration -RequireSecuritySignature $true -EnableSecuritySignature $true -EncryptData $true -Force
# Or, if you never share from this machine:
Set-SmbServerConfiguration -EnableSMB2Protocol $false -Force
```

**AnyDesk is listening on `0.0.0.0:7070`.** Either uninstall it, or restrict it to the Tailscale interface.
A remote-access tool bound to every interface, behind a disabled firewall, is a far bigger risk than any
VPN product choice in this document.

---

## 5. Part D — VPN kill-switch and leak-test checklist

### D0. Fix Proton VPN first

The `ProtonVPN WireGuard` service points at `C:\Program Files\Proton\VPN\v5.1.7\` — **a directory that does
not exist** (only `v5.1.8` and `v5.1.9` are on disk). The service is `Stopped` and cannot start, so Proton
is falling back to OpenVPN. Fix before judging speed:

```powershell
Get-Service 'ProtonVPN WireGuard','ProtonVPN Service' | Select-Object Name,Status,StartType
Get-CimInstance Win32_Service -Filter "Name='ProtonVPN WireGuard'" | Select-Object PathName
Test-Path 'C:\Program Files\Proton\VPN\v5.1.7\ProtonVPN.WireGuardService.exe'   # expect False
```

Cleanest fix: **reinstall/repair Proton VPN 5.1.9** (it rewrites the service path). Do not hand-edit service
binaries unless you accept the risk. If you already have the installer, verify it first:

```powershell
.\verify-installer.ps1 -Path .\ProtonVPN_v5.1.9_x64.exe `
  -ExpectedPublisher 'Proton AG' -ExpectedSha256 <from-proton-release-notes>
```

### D1. Enable the kill switch, then test it

In the Proton VPN client: **Settings → Kill Switch → enable**, and prefer the permanent/always-on variant if
your version offers it (a non-permanent kill switch can be defeated by a service crash or a reboot race).

The only test that counts is **killing the tunnel and watching for a leak**:

```powershell
# 1. Connect the VPN, note the exit IP
Invoke-RestMethod 'https://api.ipify.org?format=json'

# 2. Confirm the tunnel adapter is actually up
Get-NetAdapter | Where-Object Status -eq 'Up' | Select-Object Name,InterfaceDescription,LinkSpeed
Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway } | Select-Object InterfaceAlias,IPv4Address,IPv4DefaultGateway

# 3. Kill the tunnel the hard way
Stop-Service 'ProtonVPN Service' -Force
Start-Sleep -Seconds 3

# 4. This MUST fail. If it returns your ISP IP, the kill switch is not working.
try { Invoke-RestMethod 'https://api.ipify.org?format=json' -TimeoutSec 8 } catch { "BLOCKED - good: $($_.Exception.Message)" }

# 5. Restart and reconnect
Start-Service 'ProtonVPN Service'
```

### D2. Leak tests (browser)

Run each with the VPN connected, and again after D1's kill test:

| Test | URL | Pass condition |
| --- | --- | --- |
| DNS leak (standard + extended) | https://www.dnsleaktest.com/ | Resolvers belong to the VPN provider, **not** your ISP or `192.168.0.1` |
| IP / DNS / WebRTC | https://ipleak.net/ | One IP, VPN-owned; no real IP in WebRTC |
| WebRTC (dedicated) | https://browserleaks.com/webrtc | No local/public IP leak |
| Torrent leak (only if you use qBittorrent) | https://ipleak.net/ | The "Torrent Address detection" magnet shows the **VPN** IP |

**IPv6 — already handled on this box.** `ms_tcpip6` is **disabled** on the Wi-Fi adapter, which removes the
single most common VPN leak (a VPN that tunnels IPv4 but lets IPv6 escape). Verify it stays that way:

```powershell
Get-NetAdapterBinding -Name 'Wi-Fi' | Where-Object { $_.ComponentID -match 'tcpip6|^ms_tcpip$' } |
  Select-Object ComponentID,DisplayName,Enabled
```

If you ever re-enable IPv6, **only** do so with a VPN that tunnels IPv6 — otherwise you have a leak.

### D3. "Is the VPN actually up?" — one block, before any sensitive traffic

```powershell
function Test-VpnUp {
  $tunnel = Get-NetAdapter | Where-Object {
    $_.Status -eq 'Up' -and $_.InterfaceDescription -match 'WireGuard|TAP|Wintun|Proton|Mullvad|IVPN'
  }
  if (-not $tunnel) { return 'FAIL: no tunnel adapter is up' }

  $gw = Get-NetIPConfiguration | Where-Object { $_.InterfaceAlias -in $tunnel.Name -and $_.IPv4DefaultGateway }
  if (-not $gw) { return "FAIL: $($tunnel.Name) has no default gateway — traffic is not tunnelled" }

  $dns = (Get-DnsClientServerAddress -InterfaceAlias $tunnel.Name -AddressFamily IPv4).ServerAddresses
  if (-not $dns) { return "FAIL: $($tunnel.Name) has no DNS server — expect a leak" }

  try { $ip = (Invoke-RestMethod 'https://api.ipify.org?format=json' -TimeoutSec 8).ip }
  catch { return 'FAIL: egress blocked (kill switch engaged) or no connectivity' }

  [pscustomobject]@{
    Tunnel  = $tunnel.Name
    Proto   = $tunnel.InterfaceDescription
    ExitIP  = $ip
    DNS     = ($dns -join ', ')
    Verdict = if ($ip -notmatch '^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)') { 'UP' } else { 'SUSPECT' }
  }
}
Test-VpnUp
```

Run this before: banking, signing into anything with 2FA, `gh auth login`, pushing to a private remote,
opening a support session, or anything involving a credential.

**Do not run bulk Hugging Face downloads through the VPN.** 400 GB through a tunnel buys no privacy for
public artefacts you verify by hash, and it will throttle you. Verify the hash, not the tunnel:

```powershell
.\scan-weights.ps1 -Root "$env:USERPROFILE\.cache\huggingface\hub" -GenerateManifest
.\scan-weights.ps1 -Root "$env:USERPROFILE\.cache\huggingface\hub" -Verify
```

---

## 6. Part E — Installing the recommended VPN/AV, when you decide to

Nothing was installed. When you do, verify first:

```powershell
.\verify-installer.ps1 -ShowTrustedSources
.\verify-installer.ps1 -Path '.\MullvadVPN-2026.x.exe' -ExpectedPublisher 'Mullvad VPN AB' -ExpectedSha256 '<from mullvad.net download page>'
```

A `PASS` requires **all** of: SHA256 matches, Authenticode `Status=Valid`, signer Subject contains the
expected publisher, leaf certificate in date, and a timestamp countersignature. Anything else → `REFUSED`
with a non-zero exit code (1 = mismatch, 3 = unsigned, 4 = invalid signature, 5 = bad arguments).

**Remember:** a `Valid` Authenticode status alone is not authenticity — stolen and shell-company
code-signing certificates produce `Valid` signatures on malware. The publisher check and the
vendor-published hash are what make it meaningful.

### If you install a third-party AV

Defender goes to **passive mode** and **every ASR rule, Controlled Folder Access, network-protection and PUA
setting configured here stops applying.** That is the real cost of switching, and it is larger than the
+0.3 performance points you'd gain (see RECOMMENDATION.md §5.2). If you switch anyway, first record what you
are giving up:

```powershell
.\harden-defender.ps1 -Status     # capture the "before" so you can prove what changed
```

---

## 7. Part F — Maintenance

| Cadence | Action |
| --- | --- |
| Weekly | `Get-MpComputerStatus \| Select AntivirusSignatureLastUpdated,RealTimeProtectionEnabled` |
| Weekly | `.\scan-weights.ps1 -Verify -Quick` (size drift only, fast) |
| Monthly | `.\scan-weights.ps1 -Verify` (full SHA256) |
| Monthly | Re-read `(Get-MpPreference).ExclusionPath` and delete anything unrecognised |
| Monthly | `.\harden-defender.ps1 -Status` — confirm nothing silently reverted |
| Monthly | Patch check: `Get-HotFix \| Sort InstalledOn -Desc \| Select -First 5` (currently current — KB5132061/KB5132688 installed 2026-11-10) |
| Quarterly | Re-run the leak tests in D2; re-run `Test-VpnUp` |
| Quarterly | Review installed VPN/remote-access clients — remove unused ones (RiseupVPN, OpenVPN Community are redundant; TeamViewer + AnyDesk is one too many) |

### Health one-liner

```powershell
[pscustomobject]@{
  AV        = (Get-MpComputerStatus).AntivirusEnabled
  RTP       = (Get-MpComputerStatus).RealTimeProtectionEnabled
  SigAgeHrs = [math]::Round(((Get-Date) - (Get-MpComputerStatus).AntivirusSignatureLastUpdated).TotalHours,1)
  ASR       = ((Get-MpPreference).AttackSurfaceReductionRules_Ids | Measure-Object).Count
  PUA       = (Get-MpPreference).PUAProtection
  Firewall  = (Get-NetFirewallProfile | ForEach-Object { "$($_.Name)=$($_.Enabled)" }) -join ' '
  Tunnel    = (Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.InterfaceDescription -match 'WireGuard|TAP|Wintun|Proton' }).Name -join ','
} | Format-List
```

Current expected output **before hardening**: `ASR 0`, `PUA 0`, `Firewall Domain=False Private=False Public=False`.
That triple is the to-do list.

---

## 8. Change log

| Date | Change | By |
| --- | --- | --- |
| 2026-11-10 | Baseline measured. Scripts authored and smoke-tested. **No system changes applied.** | vpn-av-scout |
| — | *(next entry: whoever runs `-Apply`, with the backup filename)* | |
