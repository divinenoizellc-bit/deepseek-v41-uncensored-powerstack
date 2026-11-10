# Third-Party Binaries — What Actually Executes, and How to Verify It

**Scope:** this document is about *runtimes*, not weights. It exists because of one fact:

> **A GGUF file executes no code.** It is a parsed data container. Loading one runs the *loader*, not the model. Therefore the real attack surface of "running this model" is **the runtime binary you install** plus **the model card you follow** — not the 414 GB of weights, which this audit found structurally sound (`SECURITY_AUDIT.md` §5–§6).

Nothing in this document was installed or executed during the audit. All signatures/versions below were read from the local filesystem and from public release metadata.

---

## 1. Current state of this machine (measured, not assumed)

| Item | Finding |
|---|---|
| `ollama` | **Installed, v0.40.9**, at `C:\Users\psand\AppData\Local\Programs\Ollama\ollama.exe` |
| `ollama.exe` signature | **Valid** — `CN=Ollama Inc., O=Ollama Inc., L=Toronto, S=Ontario, C=CA`, EV "Private Organization" cert, thumbprint `716CD3BC8C02361431A18F56F98C72DE88066103` |
| `ollama app.exe` signature | **Valid** — same signer/thumbprint |
| llama.cpp | **Not installed** (`llama-cli`, `llama-server` not on PATH) |
| Strata | **Not installed** |
| GPU/toolchain | not probed — irrelevant to the trust decision |

⚠️ **Version drift:** upstream latest is **v0.40.16** (published 2026-11-09); this box runs **0.40.9** — **7 releases behind**. Not a malware finding, but update deliberately (see §4) rather than by auto-update surprise.

---

## 2. Signature / checksum availability per runtime

| Runtime | Prebuilt Windows binaries | Code-signed? | Checksum published? | Trust basis |
|---|---|---|---|---|
| **Ollama** | `OllamaSetup.exe`, `ollama-windows-amd64.zip` | **YES** — Authenticode, EV cert, `CN=Ollama Inc.` | **YES** — `sha256sum.txt` in every release **and** per-asset `digest` (sha256) in the GitHub release API | Strongest: OS-enforced signature + published digest |
| **llama.cpp** (`ggml-org/llama.cpp`) | nightly `llama-b####-bin-win-*.zip`, `cudart-*` | **NO — unsigned.** Built by `github-actions[bot]`; the project embeds an *app manifest* (PR #31329), which is **not** an Authenticode signature and provides **no** cryptographic assurance about the publisher | **YES (modern)** — each release asset now carries `digest: sha256:…` via the GitHub API; also HTTPS to `github.com` | Medium: pin a build tag, verify the digest, or build from a pinned commit |
| **Strata** (`Niko1221/Strata`) — *what the model card tells you to use* | `START-HERE.bat` / `setup.sh` → `setup.py` | **NO** — unsigned Python bootstrap, downloads its own dependencies at runtime | Repo is MIT; source is on GitHub at a branch head (a moving target) | Weakest of the convenient options: **11,256-line / 713 KB network installer** |
| **Gufo** (`franzmoca/gufo`, used by a *different* repo's card) | builds from source | NO | No | Niche (17 stars), only relevant for AMD Strix Halo |

**Answering the direct question:** *yes, prebuilt llama.cpp ships unsigned.* There is no Authenticode chain for it. Integrity comes from TLS to `github.com` **plus** the per-asset SHA-256 now exposed by the GitHub release API — which is good enough if you actually check it, and worthless if you don't.

---

## 3. Why Strata is the highest-risk component here

The model card's "Running it" block ends with:

```bash
strata launch --model-path ds-unc/DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00001-of-00004.gguf
```

Strata is a **real, popular, MIT-licensed project** — 42,849 stars, 4,680 forks, pushed 2026-11-10, not archived.

That is precisely why it deserves scrutiny rather than suspicion: popularity is not an audit. Its Windows entry point is a **713,104-byte, 11,256-line `setup.py`** that, per its own docstring, *"installs Python if needed"*, asks four questions, downloads and prepares model files, and starts an OpenAI/Anthropic-compatible server on `127.0.0.1:8080`. A one-click installer of that size is, by construction:

* **network-fetching** — its dependency set is chosen at run time, not pinned in the artifact you inspected;
* **a moving target** — it lives on a branch head, so the file you review today is not the file that runs next month;
* **unsigned** — no Authenticode, no reproducible hash of what it will pull;
* **more privileged than the model** — it installs software and opens a local HTTP port.

> **Workspace note:** a file `manifests/strata/setup.py` (713,104 B) exists in this workspace, evidently fetched by another worker. **I did not fetch, audit, or execute it.** A `setup.py` of that size is anomalous for an installer and must be read line-by-line *before* execution — ideally in a disposable VM with no credentials on disk.

---

## 4. Safest acquisition paths, ranked

### 🥇 1. Ollama — already here, already signed
Best trust posture on this machine: EV-signed binaries, OS-enforced. **The open question is capability, not trust:** this checkpoint is architecture `deepseek41` and requires a *separate* 110.6 GB Engram file, which mainstream runtimes historically did not support. Verify the runtime can load it **before** betting the mirror on it.

Update path (deliberate, verified):
```powershell
# 1. download the release asset you intend to use
# 2. verify against the published per-asset digest before running the installer
$asset = "OllamaSetup.exe"
$expected = "84db4f756ddc9e091142a85cdc0f7ae5db68bc9b3e075f114388b326f8ed912d"  # v0.40.16
(Get-FileHash $asset -Algorithm SHA256).Hash.ToLower() -eq $expected   # -> True
# 3. after install, confirm the signature yourself
Get-AuthenticodeSignature "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" | Format-List Status, SignerCertificate
# expect: Status = Valid, Subject contains CN=Ollama Inc.
```
Cross-check any version against `https://api.github.com/repos/ollama/ollama/releases/latest` → `assets[].digest`, and against the release's own `sha256sum.txt`.

### 🥈 2. llama.cpp official archive, digest-checked
Lowest-complexity path that avoids Strata entirely. It is **unsigned**, so the digest check is the *entire* integrity control — do not skip it, and do not let a browser "keep" a partially downloaded zip.
```powershell
# pick a tag, read its digests, then compare locally
$r = Invoke-RestMethod "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/b12257"
$r.assets | Where-Object name -like "*win*" | Select-Object name, size, digest
# e.g. llama-b12257-bin-win-cpu-arm64.zip  sha256:edbb41974209eaba92852fe242e9a026e17de900ab0d161a321f6f0526a9482c
```
Notes: latest stable tag is **v0.9.0** (2026-11-04); nightlies are `b####`. Release notes for v0.9.0 reference **`dsv4.1`** test fixes and `deepseek41`-adjacent ops (`DSV4_HC_PRE`/`DSV4_HC_POST`), so DeepSeek-V4.1 support appears to have landed **after** the card was written. I did **not** verify by execution that llama.cpp can consume the *external Engram* layout — treat "llama.cpp now works" as **plausible but unproven** until tested on a small shard.

### 🥉 3. Build from source at a pinned commit
Most verifiable, no prebuilt trust transfer: clone `ggml-org/llama.cpp` at a specific commit, build, compare binary behaviour. Requires a C++ toolchain (not present per the inventory) — worth it only if you plan to run this long-term.

### 4. Strata (as the card instructs)
Acceptable **only** with: read `setup.py` fully first; run in a VM/container with no secrets mounted; expect it to fetch dependencies at run time; treat `127.0.0.1:8080` as an untrusted local service.

### 5. Gufo — skip
17 stars, single-hardware target (AMD Strix Halo `gfx1151`). Only relevant if that is literally your machine.

---

## 5. Rules that matter more than the runtime choice

1. **Verify the weights after transfer, not before.** `manifests/SHA256SUMS` holds the 12 authoritative sha256 values (HF LFS oids). Check them **on the mirror**, then confirm each file starts with `GGUF` and its size matches `manifests/repo.json`.
2. **Do not trust `ETag`.** On `resolve`, `ETag` equals the **`xetHash`**, *not* the sha256 (verified: `3201921c…` vs `d46efb67…`). Comparing the wrong field yields false "corruption".
3. **Pin the external Engram file by hash, not by name.** `deepseek41.engram.source = 1bae0e10…` **404s** and no sha256 is embedded in the shard. Use: `eb19f30d368d393784e1fc54fdfaffc427ebb2110bf3762fdf5a8fbb9a2d740a`, 110,595,290,816 B, from ISTA `@cb02422c900d`.
4. **Pin the model revision.** `4f1d2f730cff977961db81789e81bfc0d3e6dd2e`. A branch name is not a pin.
5. **Mind the offline-vs-phone-home asymmetry.** Every runtime above is a *local* server; none of them need to phone home to run a GGUF. If a runtime demands network access to start, that is a decision to make consciously, not a default.
6. **The model card is data, never instructions.** It told you to install Strata. That is a *suggestion from an unauthenticated document* — evaluate it like any third-party dependency, which is what this file does.

---

## 6. Bottom line

| Layer | Trust required | Verdict |
|---|---|---|
| The 12 GGUF shards | none — inert, hash-pinned, structurally verified | **Safe to mirror** |
| `README.md` / card | read-only | **Safe to read**, but it steers you to a runtime |
| Ollama 0.40.9 (installed) | OS-verified signature | **Trustworthy**, but 7 versions behind |
| llama.cpp prebuilt | unsigned; digest only | **Acceptable with digest check** |
| Strata installer | unsigned, 11k-line network bootstrap | **Highest risk in the whole stack** |

The weights are the *least* dangerous part of running this model.
