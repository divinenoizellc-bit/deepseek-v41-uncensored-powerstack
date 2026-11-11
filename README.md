# DeepSeek-V4.1-Flash-1017 · Uncensored · Power Stack

**A verified, pinned, hardware-honest mirror + launcher for one specific model:**
[`AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF`](https://huggingface.co/AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF)
— 551,880,949,208 parameters, 384 experts, 1,048,576-token context, MIT weights, with
DeepSeek's refusal direction projected out of the dense residual writers.

This repo is **not** a weight host. It is the part that makes the weights trustworthy and
runnable: the Hub-derived SHA-256 manifest, the malware audit, the exact pins of the shared
Engram table and drafter, the packer/launcher configs, and the honest answer to "will it run
here?".

| | |
|---|---|
| **Audit verdict** | CLEAN — 0 of 16 files can execute code; 12/12 shards GGUF v3 with `SLACK = 0`; 8/12 bit-identical to upstream ISTA-DASLab, the other 4 differ *only* in size-preserving tensor edits → [`SECURITY_AUDIT.md`](Docs/security/SECURITY_AUDIT.md) |
| **Integrity** | 16 files / 352.5 GiB, every size + SHA-256 taken from the Hub's own LFS metadata → [`acceptance.json`](manifests/acceptance.json) |
| **Runtime** | [Strata](https://github.com/Niko1221/Strata) `0.2.13` / engine `0.1.59` (this model has a separate Engram file; **llama.cpp and Ollama cannot load it**) |
| **This machine** | ❌ **cannot run it** — 4 GB VRAM + 39.4 GB RAM; Strata requires ≥ 8 GB VRAM, measured at 12 GB, with 46–64 GB RAM → [`HARDWARE.md`](Docs/library/HARDWARE.md) |
| **Maxed config** | 1M context, `reasoning_effort: max`, `--speed full`, 6/6 experts, `--parallel 8`, vision on → [`POWER.md`](Docs/library/POWER.md) |

---

## What is actually going on

Three layers sit between you and the file on the Hub, and each one is a different kind of risk:

1. **Weights** — 12 GGUF shards. GGUF is a data format: it executes no code. The real risks
   are (a) a *different* repo than the one you meant to get, (b) a silently corrupt shard,
   (c) a runtime binary. This repo pins (a), hashes (b), and documents (c).
2. **Abliteration** — AtomicChat rebuilt **only the residual-writing dense tensors**
   (`attn_output_b`, `ffn_down_shexp`, `engram_wkv`) at full precision with the refusal
   direction removed (strength 2.0), then quantized them to ISTA's exact per-tensor type. The
   384 GSQ-learned routed experts are untouched. That is why 8 of 12 shards are byte-identical
   to upstream and the rest keep their exact size. Card-measured cost: KL ≈ 0.021–0.027 to the
   stock quant, MMLU unchanged within noise.
3. **A separate 103 GiB n-gram table** — "Engram". Every rung reads the *same* file, streamed
   from the SSD. It is not in the model repo and it is not optional. This is why 257 GB of
   disk is needed for a "138 GB model", and why `llama.cpp`/`Ollama` load fails: they expect
   one self-contained GGUF.

```
DeepSeek-V4.1-Flash-1017 (763B, 384 experts, MIT)
   └─ ISTA-DASLab GSQ-RCO quantization  ── 1.75 / 2.00 / 2.25 bpw  +  shared Engram IQ4_NL (103 GiB)
        └─ AtomicChat abliteration  ── dense residual writers only  ── 2.00 bpw (IQ2_XXS) ✅ + 1.75 bpw (IQ1_M) ✅
             └─ this repo  ── pin · hash · audit · pack · launch
```

## Quick start

```powershell
# 0. what would this cost me? (no downloads, no changes)
pwsh -File .\Tools\runtime\preflight.ps1

# 1. fetch the library (resumable, pinned, 352.5 GiB, ~4-6 h on a 130 Mbit line)
pwsh -File .\Tools\runtime\fetch-library.ps1

# 2. prove every byte (streams SHA-256, exits nonzero on any mismatch)
python .\scripts\verify_library.py

# 3. on a machine with a usable GPU: pack, launch, max it out
pwsh -File .\Tools\runtime\import-verified.ps1
pwsh -File .\Tools\runtime\run.ps1 -Preset nuclear
```

**If the volume cannot hold all 352.5 GiB**, the fetch script refuses the set that does not fit
instead of filling the disk. Priority order is fixed: shared files → IQ2_XXS (2.00 bpw, the rung
that passed every gate) → IQ1_M (1.75 bpw, optional). What is installed and what is deferred is
always written to [`STATUS.md`](STATUS.md), with the exact one-line command to finish the rest.

## Why two rungs and not three

`cards/rungs.json` is the publisher's own scorecard. IQ2_XS (2.25 bpw) is published with
`"pass": false` — its thinking gate drops to 2/30 and XSTest rises to 0.4%. It is also the
largest file set. It is **excluded on purpose**; both gate-passing rungs are mirrored.

| Rung | bpw | Model shards | + Engram | JailbreakBench EN | XSTest | Gate |
|---|---|---:|---:|---|---|---|
| IQ2_XXS | 2.00 | 128.8 GiB | 231.8 GiB | 85.2% → **0.0%** | 7.6% → 0.0% | ✅ pass |
| IQ1_M | 1.75 | 112.4 GiB | 215.4 GiB | 88.9% → **0.0%** | 4.8% → 0.0% | ✅ pass |
| ~~IQ2_XS~~ | ~~2.25~~ | ~~144.6 GiB~~ | ~~247.6 GiB~~ | 86.4% → 0.0% | 4.0% → 0.4% | ❌ fail |

## Repository layout

```
manifests/
  build_acceptance.py     derive accepted pins from the Hub API (--check = drift alarm)
  acceptance.json         16 files, sizes + SHA-256 = the Hub's LFS object ids
  repo.json, SHA256SUMS   the same, in the auditor's shape and in sha256sum format
  source/                 the four text artifacts, at the pinned revision
scripts/
  verify_library.py       stream-hash the local mirror; PASS/FAIL/INCOMPLETE per file+set
  index_library.py        build Library/index.json (portability verdict included)
  check_pins.py           re-query the Hub and fail loudly if a pinned file moved
  gguf_probe.py           parse a GGUF header on disk (the local half of the audit)
  status.py               live acquisition page; --write refreshes STATUS.md
  fetch.py                dependency-free resumable Range downloader (fallback to `hf`)
Tools/runtime/            preflight · fetch · import · run presets · publish · cloud kit
Tools/health/             check-all-tools.ps1 (end-to-end smoke test of every tool on the box)
Tools/harden/             Windows hardening + installer verification (see Docs/vpn-av)
configs/                  launch presets, OpenAI/Anthropic client examples
Docs/security/            SECURITY_AUDIT.md · THIRD_PARTY_BINARIES.md
Docs/library/             HARDWARE.md · POWER.md · RUNBOOK.md · PROVENANCE.md
cloud/                    provision.sh for a rented GPU + cost math
```

### Disk, while acquiring

`hf-xet` stages chunks while it assembles a 40 GB shard, so peak usage is roughly **2× the
file being written**. `fetch-library.ps1` reclaims the chunk cache after every file and refuses
to start a set that would leave less than 40 GiB free. Budget ~352.5 GiB for the library and
let it hold the peak; do not run two sets at once.

### Publishing this repo (never the weights)

```powershell
pwsh -File .\Tools\runtime\publish.ps1 -Target both -DryRun   # checks auth, pushes nothing
pwsh -File .\Tools\runtime\publish.ps1 -Target github         # needs: gh auth login
pwsh -File .\Tools\runtime\publish.ps1 -Target hf-dataset     # needs: hf auth login
```

The script refuses to publish if a tracked file is larger than 50 MB — the weights stay in
their own repos at the pins above, and this repository ships the proof, not the payload.

## Limits, stated plainly

- **This machine cannot execute the model.** Acquiring it here is archival + transferable:
  the library is portable, the manifest proves it, and a 24 GB card can run it tomorrow.
- **Enough VRAM is mandatory, not tunable.** Strata's planner refuses without it; the dense
  weights alone are ~16.8 GB and must be resident. Below the line the engine stops at start.
- **The uncensored edit is real, not cosmetic**: it removes refusals across topics on a model
  that otherwise declines. You are the only guardrail. Respect the laws that apply to you.
- **Not affiliated** with DeepSeek, ISTA-DASLab, AtomicChat or Strata. MIT tooling here;
  the weights stay under DeepSeek's MIT license, in their own repos, at the pins above.

## License

Tooling and documentation in this repository: **MIT** ([`LICENSE`](LICENSE)). Model weights:
MIT, copyright DeepSeek, redistributed by ISTA-DASLab and AtomicChat — see [`NOTICE`](NOTICE)
and [`Docs/library/PROVENANCE.md`](Docs/library/PROVENANCE.md).

