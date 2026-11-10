# VPN + Antivirus Recommendation — `DESKTOP-OFS67IF`

**Prepared:** 2026-11-10 · **Host:** Windows 11 Home 25H2 (build 26200.9711) · **Author:** vpn-av-scout
**Scope:** what this machine should run for VPN and AV, with evidence, scoring, and a costed verdict.

> **Nothing was installed or changed on this machine.** Every system change described here is
> prepared as a script with a preview default and a `-Revert` path. See
> `DEFENDER_AND_VPN_RUNBOOK.md` for the apply/verify/undo procedure.

## How to read the evidence grades

| Grade | Meaning |
| --- | --- |
| **[A]** | Primary source fetched during this session (vendor page, regulator page, lab report, Microsoft docs). Quoted specifics. |
| **[B]** | Secondary source: aggregator, law-firm alert, news report, or a primary source I could only read in part. |
| **[C]** | Vendor marketing claim or my own engineering judgement. **Not** independently verified here. |

Where a popular product is unscored, that is deliberate — see *Evidence gaps* at the end. I would rather
leave a hole than invent a number.

---

## 1. Current posture snapshot (measured, not assumed)

All values below were read from this host on 2026-11-10.

### 1.1 Host

| Fact | Value |
| --- | --- |
| OS | Windows 11 **Home** 25H2, build 26200.9711 (`EditionID=Core`) |
| CPU | AMD Ryzen 9 4900HS, 8C/16T |
| RAM | 39.4 GiB |
| GPU | RTX 2060 Max-Q 4 GB + AMD Radeon iGPU |
| Disk | CT2000P3PSSD8, 2 TB NVMe |
| User | `DESKTOP-OFS67IF\psand` — Microsoft account, **in local Administrators**, but the session token is **non-elevated** |
| Other local accounts **enabled** | `CodexSandboxOnline`, `CodexSandboxOffline`, `WsiAccount` |

### 1.2 Microsoft Defender

| Setting | Observed | Desired |
| --- | --- | --- |
| AntivirusEnabled | `True` | ✅ |
| RealTimeProtectionEnabled | `True` | ✅ |
| BehaviorMonitorEnabled | `True` | ✅ |
| AMProductVersion (platform) | `4.18.26100.4` | current platform present ✅ |
| AMEngineVersion | `1.1.26100.4` | ✅ |
| AntivirusSignatureVersion | `1.463.229.0`, updated **2026-11-10 05:53** | ✅ current |
| DefenderSignaturesOutOfDate | `False` | ✅ |
| **PUAProtection** | **`0` (off)** | `1` |
| **MAPSReporting (cloud)** | **`0` (off)** | `2` (advanced) |
| **SubmitSamplesConsent** | **`0`** | `1` |
| **EnableNetworkProtection** | **`0` (off)** | `1` |
| **EnableControlledFolderAccess** | **`0` (off)** | `2` (audit) → `1` |
| **AttackSurfaceReductionRules** | **0 rules configured** | 18 rules |
| **IsTamperProtected** | **`False`** | enable in Windows Security UI |
| FullScanAge | `4294967295` (never) | schedule one |
| QuickScanAge | 2 days | ✅ |

### 1.3 Exclusions

`Get-MpPreference` returns `ExclusionPath : {N/A: Must be an administrator to view exclusions}` — Defender
masks the list from a standard-user token, and even `HKLM:\SOFTWARE\Microsoft\Windows Defender\Exclusions\Paths`
denies read (`Requested registry access is not allowed`).

**Honest conclusion:** the exclusion list is **unverified**. It is *probably* empty, but a hidden exclusion
would be an invisible hole. Re-run `harden-defender.ps1 -Status` from an elevated shell to read it. Also note
there were **no group-policy exclusions** (`HKLM:\SOFTWARE\Policies\Microsoft\Windows Defender\Exclusions\Paths`
absent), which makes a hidden enterprise-style exclusion less likely.

### 1.4 Windows Firewall — **the most serious finding**

```
Domain Profile Settings:    State OFF
Private Profile Settings:   State OFF
Public Profile Settings:    State OFF
```

Confirmed three independent ways: `Get-NetFirewallProfile` (`Enabled=False` × 3), `netsh advfirewall
show allprofiles`, and the registry (`EnableFirewall=0` under `StandardProfile`, `PublicProfile`,
`DomainProfile`). The `mpssvc`/`BFE` services are running — the *policy* is off.

**760 firewall rules exist, 518 enabled, 427 of them inbound Allow** — all currently inert. Turning the
firewall on is not a one-click safety win: it activates 427 inbound allow rules at once. This is why the
script does **not** touch the firewall, and why the runbook treats it as a separate, supervised change.

Live exposure with the firewall off:

| Port | Bind | Process | Note |
| --- | --- | --- | --- |
| 445 SMB | `::` (all) | System | SMB2 enabled, **signing off, encryption off** → relay/NTLM risk |
| 139 NetBIOS | `192.168.0.80`, `100.66.184.13` | System | LAN + Tailscale |
| **7070** | `0.0.0.0` | **AnyDesk** | remote-access tool listening on every interface |
| 1985 | `0.0.0.0` | UnrealEditor | editor RPC |
| 1981/1989 | `0.0.0.0` | UnrealTraceServer | |
| 8686 | `0.0.0.0` | python | dev server |
| 8558 | `::` | zenserver | |
| 55446 | `0.0.0.0` | tradelocker_studio | |
| 1666 | `0.0.0.0` | p4s | |
| 135, 5040, 5357, 7680, 49664–49682 | various | OS services | RPC/SSDP/Delivery Optimization etc. |

### 1.5 Encryption (no BitLocker)

`Get-BitLockerVolume` → *"does not have an associated BitLocker volume"*. `Win32_EncryptableVolume` and
TPM queries return `Access denied` to a non-elevated token, so full-disk-encryption status is
**unconfirmed from this session**. On Windows 11 **Home** there is no BitLocker management console — only
*Device Encryption* (which requires a Microsoft account + TPM 2.0 and is usually on by default on modern
hardware). Treat as: *probably encrypted, unverified — check Settings → Privacy & security → Device encryption.*

This matters for a laptop-class machine holding model weights, keys, and session tokens. A stolen
unencrypted NVMe is a total compromise.

### 1.6 Windows Update

| KB | Type | Installed |
| --- | --- | --- |
| KB5132061 | Security Update | 2026-11-10 |
| KB5132688 | Security Update | 2026-11-10 |
| KB5127690 | Update | 2026-10-15 |
| KB5127647 | Security Update | 2026-10-14 |

**Patch level is good** — this month's security updates are already applied. `wuauserv` is Manual/Stopped
(normal, triggered on demand); `UsoSvc` is running.

### 1.7 Installed security-relevant software

| Product | Version | Publisher | Installed | Comment |
| --- | --- | --- | --- | --- |
| Proton VPN | 5.1.9 | Proton AG | 2026-11-04 | primary VPN, running |
| Proton Drive | 1.5.4 | Proton AG | 2024-06-09 | running |
| **OpenVPN 2.6.6-I001** | 2.6.601 | OpenVPN, Inc. | 2025-10-09 | **standalone Community install at `C:\Program Files\OpenVPN`** — this, not Proton, created `openvpnserv`/`openvpnserv2` |
| **RiseupVPN** | 0.24.8 | LEAP Encryption Access Project | — | **third VPN client, unused-and-unnecessary** |
| Tailscale | 1.102.3 | Tailscale Inc. | 2026-09-02 | WireGuard mesh, `100.66.184.13`, up |
| **TeamViewer** | 15.83.5 | TeamViewer | — | remote access |
| **AnyDesk** | 9.8.3 | AnyDesk Software GmbH | — | remote access, **listening on 0.0.0.0:7070** |
| qBittorrent | 4.6.3 | qBittorrent project | — | P2P client |
| Windows Defender | platform 4.18.26100.4 | Microsoft | — | only registered AV in SecurityCenter2 |

`root\SecurityCenter2\AntivirusProduct` lists **exactly one** product: `Windows Defender`
(`productState 397568` = on, signatures current). No third-party AV, and none of its leftovers.

### 1.8 Proton VPN service wiring — a real defect

```
ProtonVPN Service          Running  C:\Program Files\Proton\VPN\v5.1.9\ProtonVPNService.exe
ProtonVPN WireGuard        Stopped  C:\Program Files\Proton\VPN\v5.1.7\ProtonVPN.WireGuardService.exe ...
```

`C:\Program Files\Proton\VPN\v5.1.7\` **does not exist**. Only `v5.1.8` and `v5.1.9` are on disk. The
WireGuard helper service points at a directory deleted by an upgrade, so it can never start. The binary it
should be running exists at `v5.1.9`. A stale service registration left behind mid-upgrade.

Consequence: Proton VPN's WireGuard path is broken. The client can still fall back to OpenVPN (that
`TAP-Windows Adapter V9` / `tap0901.sys` is present and `Local Area Connection` holds a `10.41.0.1` DNS
residue from an OpenVPN session), but the **fast protocol is not available**, and the failure is silent.
This is worth fixing before any other VPN decision. Also `NTKDaemonService` (Native Instruments) has a
missing binary — cosmetic, but it is dead weight in the service table.

Also present but unused: `TAP-Windows Adapter V9` (OpenVPN), `wintun.sys` (WireGuard driver, from Tailscale
or Proton), so both tunnel drivers are already installed. Nothing new needs to be installed for a
WireGuard-based VPN.

---

## 2. Active risks found, ranked

| # | Risk | Severity | Evidence |
| --- | --- | --- | --- |
| 1 | **Windows Firewall off on all 3 profiles** with 427 inbound-allow rules and full admin rights on the box | **Critical** | §1.4 |
| 2 | **AnyDesk listening on `0.0.0.0:7070`** + firewall off + TeamViewer also installed | **High** | §1.4, §1.7 |
| 3 | **Zero ASR rules, no PUA protection, no cloud protection, no network protection, no CFA** — Defender is running at roughly *half* its capability | **High** | §1.2 |
| 4 | **SMB 445 exposed, signing and encryption off**, firewall off | **High** | §1.4 |
| 5 | FDE status unverified on a portable machine | **Medium-High** | §1.5 |
| 6 | Proton VPN WireGuard service broken (stale v5.1.7 path) | **Medium** | §1.8 |
| 7 | **Two warez-group installs** in Add/Remove: `TEAM R2R ASCEMU2`, `Valhalla DSP bundle … Team V.R`; `Cableguys … Team V.R` | **Medium** | §1.7 (install list) — pirated plugins are a classic infostealer/backdoor vector |
| 8 | Three unused/extra VPN clients (OpenVPN Community, RiseupVPN) = more surface, more drivers | **Medium** | §1.7 |
| 9 | Extra enabled local accounts (`CodexSandboxOnline/Offline`, `WsiAccount`) | **Low-Medium** | §1.1 |
| 10 | Tamper Protection reported off; Defender exclusions unauditable from this token | **Low-Medium** | §1.2, §1.3 |
| 11 | Autostart of qBittorrent + VPN means unmetered P2P exposure if the kill switch fails | **Low** | §1.7 |

Notice what is **not** in this list: "the AV is bad". Defender's signatures are current and its platform is
current. The gap is configuration, not product.

---

## 3. VPN research

### 3.1 The criteria that actually matter here

For a developer box: **(a)** an independent, *published* no-logs audit of the **infrastructure** (not just a
policy document), **(b)** jurisdiction and what it can compel, **(c)** whether you can pay without an
identity, **(d)** a kill switch that survives crashes, **(e)** WireGuard, **(f)** port forwarding (matters if
qBittorrent is used), **(g)** multi-hop, **(h)** throughput, **(i)** yearly cost, **(j)** Windows client
quality, **(k)** whether the free tier is a data-harvesting funnel.

### 3.2 Findings

#### Proton VPN — the incumbent

- Fifth consecutive annual external audit of the no-logs claim, performed by **Securitum**; Proton states
  the **full report is published**, not just a policy review. **[A]** ([protonvpn.com/blog/no-logs-audit](https://protonvpn.com/blog/no-logs-audit))
- Same source: apps are open source, there is a bug-bounty programme, and the no-logs policy has been
  "tested in over 400 legal cases" where Proton was ordered to identify users and could not. **[A]** — but
  this is Proton's own characterisation of its transparency reporting; the underlying orders are not public.
- Free tier, from Proton's own page: **1 device, no ads, no logs, unlimited and free forever**. **[A]**
  ([protonvpn.com/free-vpn](https://protonvpn.com/free-vpn)). The 1-device limit and the absence of
  streaming/P2P/port-forwarding on Free are the practical constraints. **[C]** for the
  feature-restriction detail — the free page describes what you *get*, not everything you don't.
- List pricing: **VPN Plus $9.99/mo, Proton Unlimited $12.99/mo** — **[B]**, third-party aggregator
  ([costbench.com](https://costbench.com/software/vpn/protonvpn/), "last verified Oct 20, 2026"). Proton's
  own pricing page is client-side rendered and I could not read plan prices from it. Annual-billing
  discounts are **unverified** — check at purchase.
- Already installed here at **v5.1.9**, and **Proton Drive 1.5.4 is already in use**, which makes the
  Unlimited bundle economically different from buying a second vendor outright.

#### Mullvad — the privacy-maximalist option

- Flat **€5/month**, identical for 1 month, 1 year, or 1 decade; "€5 is equivalent to $5.58"; **no sales
  ever**; 14-day refund; **5 devices**; account is a generated number, no email. **[A]**
  ([mullvad.net/en/pricing](https://mullvad.net/en/pricing))
- Payments: cash by post, Bitcoin, Bitcoin Cash, **Monero** (10 % crypto discount), bank wire, card,
  PayPal, Swish, Eps, Bancontact, iDEAL, Przelewy24. **[A]** — same page. This is the strongest anonymous
  payment matrix of any shortlisted vendor.
- **Port forwarding: removed.** Mullvad states plainly: *"Do you support port forwarding? No."* **[A]**
  (same page, linking to their removal post). **This is disqualifying** if a VPN with a working listen port
  is wanted for qBittorrent seeding.
- Sweden, `Mullvad VPN AB`, Gothenburg. **[A]**
- Independent **code** audit of GotaTun (their WireGuard implementation) by **Assured Security Consultants**,
  Jan 19 – Feb 15 2026, published 2026-03-06: *"no major vulnerabilities"*, two **low**-severity findings
  (LFSR-derived peer identifiers; missing 16-byte payload padding), both patched and shipped in
  GotaTun v0.4.0. **[A]** ([mullvad.net/en/blog/a-security-audit-of-gotatun-is-now-available](https://mullvad.net/en/blog/a-security-audit-of-gotatun-is-now-available))
- **Evidence gap:** I did **not** retrieve Mullvad's most recent *server-side no-logs* audit report in this
  session. Third-party comparisons put their audit count around ten, but that source is a vendor-comparison
  site and I am not treating it as evidence. **[C]**

#### IVPN — the no-affiliate option

- Plans changed **2026-05-08**: **Standard $60/yr** (now includes **multi-hop** and **5 devices**, up from 2),
  **Plus $80/yr** (+ Mailx email aliasing, + modDNS filtering), **Pro Suite $100/yr** (10 devices,
  + Portmaster Pro application firewall incl. SPN). **[A]**
  ([ivpn.net plan-change post](https://www.ivpn.net/blog/ivpn-plan-changes-new-plus-tier-increased-device-limits-additional-privacy-services/))
- Accounts **do not require an email address**. **[A]** (same page)
- Operated by **IVPN Limited, registered in Gibraltar**. **[A]** ([ivpn.net/en/pricing](https://www.ivpn.net/en/pricing/) footer)
- Multi-hop is now included at the cheapest tier — the best value multi-hop in this set. **[A]**
- Open-source clients, published warrant canary and transparency report. **[B]** — pages exist, I did not
  verify their currency this session.

#### NordVPN / Surfshark — not shortlisted

Both are large, competent services. I am **not scoring them** because I could not obtain independent
primary evidence (their audit reports) in this session, and every source I did reach was either the
vendor's own comparison page or an affiliate-funded review. Under the "prefer independent labs/auditors
over affiliate content" instruction, an unscored gap is the correct output. They are legitimate choices;
they are simply not *evidenced* choices here.

#### Windscribe — free tier is real but capped

- Free account = **2 GB/month**, upgraded to **10 GB/month** by confirming an email address, plus a
  one-time +5 GB for posting on X; Pro advertised at **$29/year** on a Black-Friday promo banner. **[A]**
  ([windscribe.net knowledge base](https://windscribe.net/knowledge-base/articles/can-i-use-windscribe-for-free))
- 10 GB/month is fine for occasional geo-shifting, useless for a 400 GB model-download workflow.

### 3.3 Are free VPNs safe?

The blunt answer: **a free tier from a paid vendor with a published audit is credible; a free VPN from a
company whose only product is the free VPN is a business model problem.** Proton Free has a documented
no-logs audit lineage and an identified revenue source (paid tiers). **[A]** Mullvad publishes an explicit
statement of why they have no free tier: *"'Free' services nearly always come at some cost, whether that be
the time you spend watching an intro ad, the collection of your data, or by limiting the functionality of
the service."* **[A]** ([mullvad.net/en/pricing](https://mullvad.net/en/pricing))

For this workflow, free tiers are irrelevant anyway: **1 device** (Proton Free) or **10 GB/month**
(Windscribe Free) cannot carry a Hugging Face workload.

### 3.4 VPN incident/audit notes

- The auditable good news in this set is the **code** audit (Mullvad/GotaTun, 2026) and the **recurring
  infrastructure** audit (Proton/Securitum, 5th year). **[A]**
- I found no 2025–2026 *failed* audit for any shortlisted vendor. I am explicitly **not** claiming there
  were none — only that I did not find one in the sources I could reach.

---

## 4. AV research

### 4.1 Independent lab results

**AV-TEST, six-month endurance test, published 2026-10-21** — 13 consumer suites under Windows 11 Home-class
client, test window **March–August 2026**, 800+ new zero-day samples and 35,000+ known samples, 250 fresh
zero-days per round, 12,000 dangerous reference samples, 3.5 M+ clean files for false-positives. **[A]**
([av-test.org](https://av-test.org/en/news/13-security-packages-under-windows-11-in-the-six-month-endurance-test))

| Product | Protection | Performance | Usability | **Total /18** |
| --- | --- | --- | --- | --- |
| Avast, AVG, **Bitdefender**, Kaspersky, McAfee, Norton | 6.0 | 6.0 | 6.0 | **18.0** |
| ESET | 6.0 | 5.8 | 6.0 | 17.8 |
| F-Secure | 6.0 | 5.8 | 6.0 | 17.8 |
| **Microsoft Defender** | **6.0** | **5.7** | **6.0** | **17.7** |
| TotalAV | 6.0 | 5.7 | 6.0 | 17.7 |
| Avira, K7 | 6.0 / 5.5 | 5.3 / 5.8 | 6.0 | 17.3 |
| EnigmaSoft SpyHunter | 5.2 | 6.0 | **4.7** | 15.9 |

The decisive line for this machine: **Microsoft scored full marks on protection (100 % detection of both the
real-world and reference sets) and full marks on false positives (6.0 usability). It lost 0.3 points on
*performance* — system-load overhead.** Nothing else.

**AV-Comparatives Real-World Protection Test, July–August 2026 factsheet** — released 2026-09-11, 200 live
malicious URLs, Windows 11 Pro 64-bit fully patched, false-alarm test included. **[A]**
([av-comparatives.org factsheet](https://av-comparatives.org/tests/real-world-protection-test-july-august-2026-factsheet/))
Tested set includes **Microsoft Defender Antivirus**, Bitdefender Total Security, ESET HOME Security
Essential, Kaspersky Premium, Malwarebytes **Premium**, McAfee Total Protection, Norton Antivirus Plus,
Avast One Free, AVG AntiVirus Free. Per-product percentages live in the chart image and the four-monthly
report, which I did not extract — so I cite this as corroborating *methodology and coverage*, not as numbers.

### 4.2 Per-vendor notes

**Microsoft Defender** — free, in-box, current platform, and now lab-competitive. Its unique advantage on
this machine is that it is the *only* engine that exposes **ASR rules, Controlled Folder Access, network
protection and PUA protection** with no extra agent. All of that is available on **Windows 11 Home** —
Microsoft states ASR rules are "available on any edition of Windows that includes Microsoft Defender
Antivirus (for example, Windows 11 Home)". **[A]**
([learn.microsoft.com ASR reference](https://learn.microsoft.com/en-us/defender-endpoint/attack-surface-reduction-rules-reference), updated 2026-09-09)
That is the single most important technical fact in this document: **you can meaningfully harden Defender
on Home**, which most "Defender is only average" advice ignores.

**Bitdefender** — 18/18 across the board in the 2026 endurance test, including a full 6.0 on performance. **[A]**
Romania. The best-measured product in the set.

**ESET** — 17.8/18; 6.0 protection, 5.8 performance, 6.0 usability. **[A]** Slovakia. Historically the
lightest-touch suite on developer workloads. **[C]** for the dev-workload reputation — the lab does not
measure "does it break MSBuild".

**Kaspersky** — technically excellent (18/18 **[A]**), and **not an option on this machine**. The US
Department of Commerce's BIS issued the **first-ever ICTS supply-chain prohibition** against Kaspersky
software, with a prohibition effective **2024-09-29**. **[B]** — law-firm alerts summarising the final
determination ([Nixon Peabody](https://content.nixonpeabody.com/-/media/files/alerts/2024/06/final-determination-prohibiting-russian-kaspersky-software.pdf),
[Crowell](https://www.crowell.com/print/v2/content/94181/growing-technology-supply-chain-risks-kaspersky-lab-software-banned-in-first-use-of-icts-supply-chain-prohibition.pdf)).
The box is in the US (America/Phoenix). **Excluded on regulatory grounds regardless of merit.**

**Norton / McAfee** — lab scores are now top-tier (both 18/18 **[A]**), which makes the *product* argument
weak and the *business-practice* argument decisive. The FTC took action over LifeLock auto-renewal dark
patterns, resulting in **$100 M** to be paid to consumers for violating a 2010 order. **[B]** — I could only
retrieve the FTC's Spanish-language press release ([ftc.gov](https://www.ftc.gov/es/noticias/lifelock-les-pagara-100-millones-de-dolares-los-consumidores-afectados-para-resolver-los-cargos-de-la-ftc-por-infringir-una-orden-del-ano-2010));
the English page returned HTTP 403. Same class of conduct, same vendor family.

**Avast / AVG** — 18/18 **[A]**, and the worst privacy record in the set: the FTC finalised an order
**banning Avast from selling or licensing web-browsing data for advertising** and requiring **$16.5 M** over
charges it sold browsing data *after* claiming its products blocked tracking. **[A]**
([FTC final order](https://www.ftc.gov/news-events/news/press-releases/2024/06/ftc-finalizes-order-avast-banning-it-selling-or-licensing-web-browsing-data-advertising-requiring-it)),
with a consumer refund process announced later **[A]**
([FTC refund notice](https://search.ftc.gov/news-events/news/press-releases/2025/02/ftc-announces-refund-claims-process-avast-customers-impacted-deceptive-privacy-claims)).
For a user whose stated priority is "privacy by default", installing this is incoherent.

**Malwarebytes** — correct role is **on-demand second opinion**, not primary. The free edition is a manual
scanner with no real-time protection. **[C]** AV-Comparatives tests the *Premium* SKU, not Free. **[A]**

**TotalAV / SpyHunter (EnigmaSoft)** — both are in the lab set. SpyHunter is the only product that failed
the false-positive category (**4.7 usability**), i.e. it blocks harmless programs. **[A]** Both are marketed
heavily through affiliate "PC cleanup" funnels. Avoid.

### 4.3 2025–2026 incidents worth knowing

- **An antivirus vendor was compromised and pushed a malicious update.** A widely-reported incident in the
  period involved an AV update server being hacked to distribute malicious update packages. **[B]** — I
  reached the write-up ([TechRadar](https://www.techradar.com/pro/security/top-antivirus-hacked-to-push-out-a-malicious-update-find-out-if-youre-affected))
  but the article body was truncated by the fetch, so I will not name the product or the mechanics beyond
  the headline. The lesson stands and is the important part: **the AV agent is itself a supply-chain target
  running at highest privilege.** Fewer agents = smaller target. This argues *against* stacking a second
  real-time AV on this box.
- **AI-model repositories are a live malware vector.** Multiple 2026 reports describe malicious models and
  agent skills planted in model/skill hubs. **[B]** ([TNW](https://thenextweb.com/news/hugging-face-clawhub-malware-ai-supply-chain) —
  headline and lede only; body truncated). This is directly this machine's threat model, and it is the
  reason `scan-weights.ps1` exists and the reason the AV choice is *not* the load-bearing control here.

---

## 5. Decision matrix

Scores 1–5 (5 = best) for **this** machine and workflow. "Conf." = evidence confidence.

### 5.1 VPN

| Criterion | Proton VPN | Mullvad | IVPN | NordVPN | Surfshark | Windscribe |
| --- | --- | --- | --- | --- | --- | --- |
| Independent published no-logs audit | **5** [A] | 4 [C] | 4 [B] | – | – | 2 [C] |
| Jurisdiction | **4** (CH) [A] | **5** (SE) [A] | **5** (GI) [A] | – | – | 3 [C] |
| Anonymous payment | 3 (card/PayPal/crypto) [C] | **5** (cash, Monero) [A] | 4 [C] | – | – | 3 [C] |
| Kill switch / leak protection | 4 [C] | **5** [C] | **5** [C] | – | – | 3 [C] |
| WireGuard | **5** [A] (present, but *service broken here* — §1.8) | **5** [A] | **5** [B] | – | – | 4 [C] |
| Port forwarding | **5** [C] | **0** (removed) [A] | 4 [B] | – | – | **5** [C] |
| Multi-hop | 4 [C] | 4 [C] | **5** (in $60 tier) [A] | – | – | 3 [C] |
| Price / year | 3 ($120 list) [B] | **5** (€60) [A] | **5** ($60) [A] | – | – | **5** ($29 promo) [A] |
| Windows client quality | **5** [A] | 4 [A] | 4 [B] | – | – | 3 [C] |
| Free tier is safe | **5** (audited, no ads) [A] | n/a (none, by design) [A] | n/a | – | – | **5** (10 GB, honest) [A] |
| **Total /55** | **43** | **37** | **44** | – | – | **33** |

NordVPN and Surfshark are **unscored** — not because they are bad, but because I have no primary evidence
to score them on. Never let a matrix row of dashes read as a zero.

### 5.2 AV

| Criterion (weight) | Defender | Bitdefender | ESET | Kaspersky | Norton | McAfee | Avast/AVG | Malwarebytes Free |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Lab protection (×3) | 5 [A] | 5 [A] | 5 [A] | 5 [A] | 5 [A] | 5 [A] | 5 [A] | 3 [C] |
| False positives (×3) | **5** [A] | 5 [A] | 5 [A] | 5 [A] | 5 [A] | 5 [A] | 5 [A] | 3 [C] |
| Performance overhead (×2) | 4 [A] | **5** [A] | 4 [A] | 5 [A] | 5 [A] | 5 [A] | 4 [A] | 5 [C] |
| Dev-tool tolerance (×2) | **5** (tunable, ASR-aware) [C] | 4 [C] | 4 [C] | 3 [C] | 2 [C] | 2 [C] | 3 [C] | **5** |
| No bloat / upsell (×2) | **5** [A] | 3 [C] | **5** [C] | 3 [C] | 1 [B] | 1 [B] | 1 [A] | 4 [C] |
| Privacy / telemetry (×2) | 4 [C] | 4 [C] | 4 [C] | 2 [B] | 2 [C] | 2 [C] | **1** [A] | 4 [C] |
| Cost / yr (×1) | **5** ($0) | 2 [C] | 2 [C] | – | 2 [C] | 2 [C] | **5** ($0) | **5** ($0) |
| Works with Defender's ASR layer (×1) | **5** | 0 (replaces it) | 0 | 0 | 0 | 0 | 0 | **5** |
| **Weighted total /80** | **72** | 63 | 65 | 50 | 47 | 47 | 50 | 60 |

The row that decides it for a hardened dev box is the last one. **Any third-party real-time AV puts Defender
into passive mode, which switches off every ASR rule, Controlled Folder Access, network protection and PUA
protection we just configured.** You would be trading a *measurably near-perfect* detection score for a
*theoretically slightly better* one, and deleting the behavioural layer that actually catches
"fresh unsigned binary doing something odd" — which is this machine's real risk.

---

## 6. Verdict

### PRIMARY VPN → **Keep Proton VPN. Fix it, don't replace it.**

Proton VPN is **good enough to keep**, and switching would be spending money to solve a problem you don't
have. It has a 5th-year published no-logs infrastructure audit, open-source clients, a documented
court-tested no-logs record, and it is already installed, configured, and paired with Proton Drive. **[A]**

But it is **currently degraded on this box**: the `ProtonVPN WireGuard` service points at
`v5.1.7\ProtonVPN.WireGuardService.exe`, a directory the upgrade deleted (§1.8). Fix that service
registration (or reinstall 5.1.9 cleanly) before judging the VPN's speed. **A broken tunnel helper is not a
vendor quality problem — it is a local install problem.**

Do this *only if* your Proton tier is Free and you need more than 1 device or P2P: upgrade to a paid Proton
tier, or move to Mullvad/IVPN below. For the 400 GB Hugging Face workflow, the VPN should be **off** during
bulk downloads anyway (§8).

### OPTIONAL second layer → **Mullvad (€60/yr) *or* IVPN Standard ($60/yr) — pick at most one**

Add a second provider only for **provider diversity**, not for "more protection":

- **Mullvad €60/yr (~$67)** if you want to pay by **cash or Monero** and have **no account identity at all**,
  plus a code-audited WireGuard stack. **[A]** **Caveat: no port forwarding.** **[A]** That rules it out as
  your qBittorrent VPN.
- **IVPN Standard $60/yr** if you want **multi-hop included at the base tier**, no email required, Gibraltar
  jurisdiction, and a company that publicly refuses affiliate marketing. **[A]** Better fit for this box.

Running two VPN clients at once on Windows is a genuinely bad idea — competing tunnel adapters, routing
metric fights, and a kill switch that will happily block the other. **Use one at a time.** The realistic
"second layer" here is not a second VPN client: it is **Tailscale** (already running) for private access,
plus the leak discipline in the runbook.

### PRIMARY AV → **Microsoft Defender. Yes, alone is sufficient — but only hardened.**

With the hardening applied it scores **72/80** on the criteria that matter here, has **100 % lab detection
and a perfect false-positive score** **[A]**, and it is the only engine that gives you the ASR/CFA layer on
Windows 11 Home. Adding a second real-time AV would *reduce* your effective protection by disabling that
layer, and would add a second high-privilege agent to the supply-chain attack surface.

The unsentimental version: **Defender is not your weakest link. Your firewall being off is** (§1.4). Fix
that first.

### Paid upgrade actually worth it → **probably none; if you must, Bitdefender (not ESET, not Norton)**

Be clear about what you'd buy. You would be buying **+0.3 performance points** and a different UI. You would
be **selling** the ASR/CFA layer and adding a second agent. That is a bad trade for a dev box.

If a business or compliance reason forces third-party AV: **Bitdefender Total Security** is the best-measured
product in the set (18/18, including full performance marks) **[A]**; **ESET** is the credible lighter-touch
alternative (17.8, 5.8 performance) **[A]**. Do **not** choose Norton, McAfee, or Avast/AVG — not on
detection, which is fine, but on business conduct (FTC $100 M LifeLock; FTC $16.5 M Avast browsing-data ban).
**[A]/[B]**

### ON-DEMAND second opinion → **Malwarebytes Free + VirusTotal hash lookups**

Malwarebytes Free as a manual scanner you run when something feels wrong. Plus **`scan-weights.ps1`** for
the actual model-repo threat model, and **VirusTotal by SHA256** (hash lookup, no upload) for anything small
and suspicious. Do **not** buy Malwarebytes Premium as your primary — it is a fine product in the wrong role.

### WHAT TO AVOID, and why

| Avoid | Why | Evidence |
| --- | --- | --- |
| **Kaspersky** | BIS ICTS prohibition effective 2024-09-29; top-tier lab scores are irrelevant to a US machine | [B] BIS alerts |
| **Norton / LifeLock** | FTC: **$100 M** consumer payout over dark-pattern auto-renewal violating a 2010 order | [B] FTC |
| **McAfee** | Same auto-renewal/upsell dark-pattern profile; heavy upsell engine | [B], [C] |
| **Avast / AVG** | FTC: **$16.5 M** + ban on selling browsing data for advertising, *after* claiming to block tracking | [A] FTC |
| **TotalAV / SpyHunter** | Affiliate funnel marketing; SpyHunter is the only suite to fail the false-positive test (4.7) | [A] AV-TEST |
| **Free standalone VPN apps** | Business model is the data or the upsell; no published infrastructure audit | [C] |
| **Affiliate "Top 10 VPN 2026" lists** | Commission-driven; the ranking tracks payout, not audits | [C] |
| **Stacking a 2nd real-time AV** | Disables ASR/CFA; doubles the privileged-agent supply-chain surface | [C] |
| **The `Team V.R` / `R2R` warez plugins on this box** | Pirated audio plugins are a textbook infostealer/backdoor vector and run with your user's rights | §1.7 |

---

## 7. Cost per year

| Item | USD/yr | EUR/yr | Source |
| --- | --- | --- | --- |
| Microsoft Defender | **$0** | €0 | in-box |
| Malwarebytes Free | **$0** | €0 | scan-only tier |
| `scan-weights.ps1` / `verify-installer.ps1` | **$0** | €0 | this repo |
| **Keep Proton VPN** | already paid / $0 to $120 list | — | $9.99/mo list **[B]** |
| **+ Mullvad (optional 2nd)** | ~**$67** | **€60** | €5/mo flat **[A]** |
| **+ IVPN Standard (optional 2nd)** | **$60** | ~€55 | **[A]** |
| Bitdefender Total Security (if forced) | not verified here | — | check vendor |
| ESET (if forced) | not verified here | — | check vendor |

**Recommended spend: $0 to $60/yr.** The honest recommendation for this box is:
spend **nothing** on AV, spend **$0–60** on VPN (keep Proton; add IVPN Standard only if you want
multi-hop/provider diversity), and spend the money you saved on a second NVMe for backups.

I have deliberately not published Bitdefender/ESET prices — I did not verify them from a primary source in
this session, and stale prices in a cost table are worse than a blank cell.

---

## 8. What a VPN does NOT protect you from

This is the section that matters most, because "I have a VPN" is the most common false sense of security.

**A VPN changes your IP address and encrypts traffic between you and the exit node. That is all.**

It does **not** protect you from:

1. **Malware inside a model repo.** A `.pkl` that executes on load does so after decryption. The VPN inspects
   nothing. This is why `scan-weights.ps1`, pinned revisions, and `safetensors` exist.
2. **A malicious model uploaded to a hub.** Popular-repo impersonation is an account-compromise problem, not
   a network-privacy problem. **[B]** ([TNW 2026 report](https://thenextweb.com/news/hugging-face-clawhub-malware-ai-supply-chain))
3. **Supply-chain compromise in `pip`/`npm`/`git`.** Package installers run with your rights regardless of tunnel.
4. **Phishing, credential theft, session-token theft.** `pip install` from a typosquat, or a fake login page,
   works identically behind a VPN.
5. **Exploits against unpatched Windows or software.** Patch level, not tunnel state, decides this.
6. **Anything already on the box.** AnyDesk on `0.0.0.0:7070`, SMB on 445, extra enabled local accounts — a
   VPN does not close a listening port.
7. **Local-network attackers.** ARP spoofing, rogue DHCP, a hostile LAN — a VPN only helps if it carries
   *all* traffic *and* the kill switch holds.
8. **Anything you are logged into.** Google/Microsoft/GitHub see your account, not your IP. Your browser
   fingerprint is largely IP-independent.
9. **Data you upload.** Hugging Face, GitHub, cloud backups — the VPN does not anonymise the payload.
10. **Legal compulsion of the provider.** A no-logs design is what protects you, and only if it is real,
    audited, and enforced — which is exactly why audit evidence is criterion #1 in §3.1.
11. **The hostage situation of a single point of failure.** A VPN provider outage, or a broken WireGuard
    service (§1.8), does not make you more private; it makes you either offline or naked, depending on the
    kill-switch configuration.

**And specifically:** downloading 400 GB of model weights **through** a VPN is counterproductive. You pay
in throughput, you stress the provider's AUP, and you gain nothing — the bytes are public artefacts whose
integrity you verify by hash, not by tunnelling them. **Verify the hash, not the tunnel.**

---

## 9. Exact next actions, in order

| # | Action | Owner | Risk |
| --- | --- | --- | --- |
| 1 | **Turn Windows Firewall on** and reconcile the 427 inbound-allow rules first (supervised; runbook §3) | you | medium — can break Unreal/AnyDesk/Python dev servers |
| 2 | **Run `harden-defender.ps1 -Apply`** from an elevated shell (ASR, PUA, cloud, network protection, CFA audit, SmartScreen, model exclusions) | you | low, reversible with `-Revert` |
| 3 | **Enable Tamper Protection** in Windows Security → Virus & threat protection → Manage settings | you | none |
| 4 | **Fix the Proton VPN WireGuard service** (§1.8) or reinstall 5.1.9 | you | low |
| 5 | **Remove AnyDesk** if you don't actively use it; if you do, bind it to Tailscale only and never `0.0.0.0` | you | low |
| 6 | **Uninstall RiseupVPN + OpenVPN Community** (redundant clients/drivers) | you | low |
| 7 | **Confirm Device Encryption** is on (Settings → Privacy & security → Device encryption) | you | none |
| 8 | **Run `scan-weights.ps1 -GenerateManifest`** on `C:\Users\psand\Models` and the HF cache to pin a baseline | you | none, read-only |
| 9 | **Delete the `Team V.R` / `R2R` warez plugins**; re-buy or remove | you | none |
| 10 | Disable `CodexSandboxOnline/Offline`/`WsiAccount` if nothing needs them | you | low |
| 11 | Enable SMB signing + encryption, or disable SMB server if unused | you | low |
| 12 | Schedule a monthly full scan (never run) | you | low (I/O) |

---

## 10. Evidence gaps (things I did not verify, stated plainly)

1. **Defender's actual exclusion list** — masked from a non-elevated token (§1.3). Elevated
   `harden-defender.ps1 -Status` resolves it.
2. **Proton VPN annual pricing** — the pricing page is client-rendered; only the $9.99/$12.99 monthly list
   from a third-party aggregator is available here. **[B]**
3. **Mullvad's most recent server-side no-logs audit report** — not retrieved. Only their GotaTun *code*
   audit is verified here. **[A]** for GotaTun, gap for the infrastructure audit.
4. **NordVPN / Surfshark** — no primary audit evidence reached; deliberately unscored.
5. **Bitdefender / ESET list prices** — not verified; omitted from the cost table.
6. **Device Encryption / BitLocker state** — access denied to a non-elevated token (§1.5).
7. **The AV-update-server compromise and the AI-hub malware reports** — headlines/ledes only; the fetched
   article bodies were truncated, so no product names, dates or mechanics are asserted beyond the headlines.
8. **AV-Comparatives per-product percentages** for Jul–Aug 2026 — the numbers are in a chart image plus the
   four-monthly report; cited for methodology and coverage only.

---

## 11. Sources

**Labs / regulators / primary documentation**
- AV-TEST, *13 security packages under Windows 11 in the six-month endurance test*, 2026-10-21 — https://av-test.org/en/news/13-security-packages-under-windows-11-in-the-six-month-endurance-test
- AV-Comparatives, *Real-World Protection Test July–August 2026 — Factsheet*, released 2026-09-11 — https://av-comparatives.org/tests/real-world-protection-test-july-august-2026-factsheet/
- Microsoft Learn, *Attack surface reduction rules reference*, updated 2026-09-09 — https://learn.microsoft.com/en-us/defender-endpoint/attack-surface-reduction-rules-reference
- FTC, *Final order with Avast… $16.5 Million*, 2024-06 — https://www.ftc.gov/news-events/news/press-releases/2024/06/ftc-finalizes-order-avast-banning-it-selling-or-licensing-web-browsing-data-advertising-requiring-it
- FTC, *Refund claims process for Avast customers* — https://search.ftc.gov/news-events/news/press-releases/2025/02/ftc-announces-refund-claims-process-avast-customers-impacted-deceptive-privacy-claims
- FTC, *LifeLock to pay $100 million…*, (ES edition; EN returned 403) — https://www.ftc.gov/es/noticias/lifelock-les-pagara-100-millones-de-dolares-los-consumidores-afectados-para-resolver-los-cargos-de-la-ftc-por-infringir-una-orden-del-ano-2010

**VPN vendors (primary)**
- Proton VPN, *For 5th year running, Proton VPN passes external no-logs audit* (Securitum) — https://protonvpn.com/blog/no-logs-audit
- Proton VPN, *Free VPN* — https://protonvpn.com/free-vpn
- Mullvad, *Pricing* — https://mullvad.net/en/pricing
- Mullvad, *A security audit of GotaTun is now available*, 2026-03-06 — https://mullvad.net/en/blog/a-security-audit-of-gotatun-is-now-available
- IVPN, *Plan changes — new Plus tier…*, 2026-05-08 — https://www.ivpn.net/blog/ivpn-plan-changes-new-plus-tier-increased-device-limits-additional-privacy-services/
- IVPN, *Pricing* — https://www.ivpn.net/en/pricing/
- Windscribe, *Can I use Windscribe for Free?*, 2026-01-06 — https://windscribe.net/knowledge-base/articles/can-i-use-windscribe-for-free

**Secondary**
- CostBench, *Proton VPN Pricing 2026* (verified 2026-10-20) — https://costbench.com/software/vpn/protonvpn/
- Nixon Peabody, *Final determination prohibiting Russian Kaspersky software* (2024) — https://content.nixonpeabody.com/-/media/files/alerts/2024/06/final-determination-prohibiting-russian-kaspersky-software.pdf
- Crowell, *Kaspersky Lab software banned in first use of ICTS supply chain prohibition* — https://www.crowell.com/print/v2/content/94181/growing-technology-supply-chain-risks-kaspersky-lab-software-banned-in-first-use-of-icts-supply-chain-prohibition.pdf
- TechRadar, *Top antivirus hacked to push out a malicious update* — https://www.techradar.com/pro/security/top-antivirus-hacked-to-push-out-a-malicious-update-find-out-if-youre-affected
- TNW, *Hugging Face and ClawHub compromised with hundreds of malicious AI models…* — https://thenextweb.com/news/hugging-face-clawhub-malware-ai-supply-chain
