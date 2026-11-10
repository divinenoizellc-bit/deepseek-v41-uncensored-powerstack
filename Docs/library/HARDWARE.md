# Will it run here? — hardware reality

**Short answer for the machine this library was built on: no.** It is a 6 GiB-VRAM / 39.4 GiB-RAM
laptop. The runtime's own planner refused it, in its own words, before downloading anything.
The library is still worth having — it is portable, hash-proven, and a 24 GB card runs it — but
nothing here will make 551.9 B parameters fit in 6 GiB.

Evidence is in [`Library/logs/strata-plan-2.00bpw.log`](../../Library/logs/strata-plan-2.00bpw.log),
produced by `strata launch --plan --family deepseek41 --model ist-das-2.00bpw` on 2026-11-10.

```
Plan for 'IST-DAS-2.00bpw 128K':
  model     DeepSeek-V4.1-Flash IST-DAS-2.00bpw, 257 GB
  context   128K    pictures on    parallel one at a time
  download  About 256.8 GB to download.
  placement
    - ...138 GB of model, 111 GB n-gram table, 8 GB drafter...
    - The n-gram table stays on the SSD and is read a few rows for each word
  [!] No graphics card Strata can use was found: this model needs one or more cards
      (8 GB or more; 12 GB is what it was measured with).
  [!] DeepSeek-V4.1-Flash IST-DAS-2.00bpw: may run slower.
Nothing was changed.
```

---

## The shape of the problem

| Quantity | Value | Consequence |
|---|---:|---|
| Parameters | 551,880,949,208 | 384 experts, 40 layers, 6 experts routed per token |
| Weights, 2.00 bpw set | 128.8 GiB in 4 shards | must exist somewhere reachable at memory speed |
| Engram n-gram table | 103.0 GiB, one file | shared by every rung; **streamed from the SSD every token** |
| DSpark drafter | 7.4 GiB | optional; `--dspark auto` decides per machine |
| Vision tower | 0.9 GiB | needed only for image input |
| **Total library** | **352.5 GiB** | the exported shapes: `Library/index.json` |
| Dense (non-expert) weights | ≈ 16.8 GB | **must be VRAM-resident** — "about 16 GB on one card" |
| KV/attention cache | grows with context | 1M ctx is offered, not tested; it steals expert room |
| Routed experts | 288.8 GB at ~2 bpw | whichever do not fit in VRAM are computed on the CPU from the model files |

Strata documents the failure mode explicitly: a card that cannot hold its share of the dense
weights **stops at start with an out-of-memory message**; below ~40 GB of RAM the model is
"untested and slow". This machine has **6 GiB VRAM** (nvidia-smi: 6144 MiB, driver 610.88, compute 7.5 — WMI reports 4 GiB because AdapterRAM is a 32-bit field) and **39.4 GiB RAM (≈19 GiB free)**.

Both numbers are below the line, and only one of them is a settings problem.

## Reference points the vendor measured

| Hardware | RAM | Output | Prompt |
|---|---:|---:|---:|
| RTX 3060 12 GB | 46 GB | 9–11 tok/s | ~155 tok/s (4K) |
| RTX 5070 12 GB | 64 GB | 4–6 tok/s | ~110 tok/s (4K) |
| RTX 4090 24 GB (a user's own sm_89 build) | 128 GB | ~40 tok/s | 141 tok/s (1.2K) |
| 4 × Radeon AI PRO R9700 | 251 GB | 48–80 tok/s | 320–450 tok/s |

Minimum is **8 GB VRAM** by the planner; 12 GB is the measured floor for a good experience.

## Why "just try harder" does not apply

1. **VRAM is a hard gate, not a knob.** Dense weights are resident by design. There is no
   supported "keep dense weights on the CPU" switch in `strata launch --help`.
2. **The prebuilt Windows DeepSeek engine has no Turing code.** Its packages carry sm_86 (RTX 30),
   sm_89 (RTX 40), sm_120 (RTX 50) plus PTX for sm_120. An RTX 2060 Max-Q is **sm_75**. A
   source build with `-DCMAKE_CUDA_ARCHITECTURES=75` is documented, and this box has no CUDA
   toolkit, no CMake and no C++ compiler anyway — and building it would still hit gate 1.
3. **Ollama and llama.cpp cannot serve this model.** DeepSeek-V4.1-Flash keeps its n-gram table
   in a second file; llama.cpp has no loader for it (the model card says so, and Strata's docs
   repeat it). Every `ollama create` path is a dead end for this model, regardless of VRAM.

## What this machine *is* good for

- **Acquire and prove the library** — 352.5 GiB on a 2 TB NVMe, every shard verified against
  the Hub's LFS SHA-256. That is what is running now, and it is genuinely portable.
- **Run a small abliterated model fast** — e.g. the Qwen2.5-7B abliterated build already in
  Ollama on this box answers at interactive speed on the same 4 GB card. Different league of
  model, but it actually runs.
- **Control and serve a remote one** — the client side needs no GPU at all: `strata connect`,
  or any OpenAI-compatible client pointed at a rented box (see [`RUNBOOK.md`](RUNBOOK.md)).

## Path to actually running *this* model

| Path | Cost | Time to first token | Notes |
|---|---|---|---|
| Rent 1× RTX 4090 24 GB / 64 GB RAM / 300 GB NVMe | ≈ $0.35–0.60/h | ~10 min setup + 20 min model load | sm_89 is supported; user-measured ~40 tok/s |
| Rent 1× L40S 48 GB / 96 GB RAM | ≈ $0.80–1.20/h | same | headroom for 256K ctx |
| Own 1× RTX 3060 12 GB + 64 GB RAM | ≈ $400–600 | one-off | 9–11 tok/s, the vendor's own reference box |
| Strix Halo 128 GB unified | ≈ $2k | one-off | 11–21 tok/s; whole model on one chip |

The library is transportable: copy the folder, re-run `scripts/check_pins.py` and
`scripts/verify_library.py` on the target, then `Tools/runtime/import-verified.ps1`.

