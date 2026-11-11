# RUNBOOK — acquire, prove, launch, connect

Two lanes. Lane A is this machine (acquire + prove only). Lane B is a machine with a usable GPU.

---

## Lane A — here (no GPU that can run it)

```powershell
cd "C:\Users\psand\Desktop\Harness Machine\deepseek-v41-uncensored-powerstack"

# what it will cost, before a byte moves
pwsh -File .\Tools\runtime\preflight.ps1

# 352.5 GiB, resumable, pinned; re-run after any interruption
pwsh -File .\Tools\runtime\fetch-library.ps1 -Set all

# prove it: streams SHA-256, exit 0 only when every file matches
python .\scripts\verify_library.py

# index it (writes Library/index.json, includes the portability verdict)
python .\scripts\index_library.py
```

Expected end state: `16/16 PASS`, `352.5 GiB`, exit code 0. Anything else is not a working
library — a 39 GB shard that is one byte short will still "load" and then emit garbage.

---

## Lane B — a machine with ≥ 12 GB VRAM and ≥ 48 GB RAM

### B1. Install the runtime (verified)

```powershell
# Windows: the Terminal installer verifies its own SHA-256 and Strata's signed feed
& .\Tools\runtime\install-strata.ps1        # wraps the official install.ps1 with checksum pinning
```

The installer needs no administrator rights and writes to `%LOCALAPPDATA%\Strata`.

### B2. Prove the hardware before downloading 257 GB

```powershell
strata launch --plan --family deepseek41 --model ist-das-2.00bpw
```

If it prints `No graphics card Strata can use was found`, stop: the model cannot start, and
nothing else in this runbook will change that.

### B3. Import the verified local library

```powershell
pwsh -File .\Tools\runtime\import-verified.ps1 -Rung IQ2_XXS
```

That script verifies hashes first, then hands the folder to Strata with `--model-path`
(a folder of shards is accepted). It refuses to import a file whose SHA-256 is not in
`manifests/acceptance.json`.

> **Known friction, by design:** our shard `…-IQ2_XXS-00004-of-00004.gguf` has the same size as
> ISTA's but a different SHA-256 (the abliteration). Strata's *own* downloader compares against
> ISTA's pins; the `--model-path` / `models import` path packs files you already have. If a build
> refuses the set, use the packer directly:
> `python tools/dsv41/pack_gguf.py --model <dir> --out <pack> --engram DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf --engram-meta UD-Q8_K_XL/DeepSeek-V4.1-Flash-1017-UD-Q8_K_XL-00001-of-00009.gguf`
> from the Strata checkout.
>
> **Measured, not assumed** — `strata models import --plan <library>` on the finished library says:
>
> ```
> 5 GGUF file(s): plausible
> These files are Strata's deepseek41 IST-DAS-2.00bpw.
> Prepared files found beside it: picture reader.
> Adoption: requires_name_size_sha256_and_engine_checks
> No files changed
> ```
>
> So the layout, the split, the Engram and the vision tower are all recognised as the right model;
> the only remaining gate is the hash check (`requires_name_size_sha256_and_engine_checks`), which
> is where shard 4's abliterated hash differs from ISTA's pin. That is the expected behaviour of an
> edited set, not a packaging error.

### B4. Launch

```powershell
pwsh -File .\Tools\runtime\run.ps1 -Preset balanced   # 128K, full quality, 4 parallel
pwsh -File .\Tools\runtime\run.ps1 -Preset nuclear    # 1M ctx, 6/6 experts, 8 parallel
```

Server: `http://127.0.0.1:8080` — OpenAI at `/v1`, Anthropic Messages at `/v1/messages`.

### B5. Connect clients

```powershell
strata connect                      # list adapters
strata connect claude-code          # print settings for Claude Code
strata connect codex                # print settings for Codex CLI
strata connect opencode --write     # write config for opencode
strata connect claude-code --check --output json   # one prompt + one tool call
```

Anything that speaks OpenAI Chat Completions works with `base_url: http://127.0.0.1:8080/v1`
and a key from `strata launch --show-key`. `configs/openai_client.py` and
`configs/anthropic_client.py` are dependency-free examples.

### B6. Benchmark, then tune

```powershell
python .\Tools\runtime\bench.py --url http://127.0.0.1:8080/v1 --model deepseek-v4.1-flash --runs 5
```

Re-run for each flag change. See [`POWER.md`](POWER.md) for what moves the needle.

---

## Lane C — rent the GPU, keep the control plane here

1. Rent a Linux box: 1× RTX 4090 24 GB / 64 GB RAM / 300 GB NVMe (sm_89 is in the engine
   package). Cost ≈ $0.35–0.60/h.
2. On the rented box: `bash cloud/provision.sh` — installs Strata, downloads the pinned 2.00 bpw
   set, verifies against our manifest hashes, launches with the `balanced` preset, binds to
   localhost.
3. Tunnel: `ssh -L 8080:127.0.0.1:8080 user@host`.
4. Point local clients at `http://127.0.0.1:8080/v1` — zero GPU needed locally.

Details and cost math: [`cloud/README.md`](../../cloud/README.md).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `No graphics card Strata can use was found` | VRAM below the floor (or a Turing card with no engine build) | different hardware; nothing to tune |
| Engine exits at start with out-of-memory | dense weights cannot be resident | lower `--context`, `--vision off`, `--parallel 1`; still needs ≥ 8 GB |
| Answers are garbage / repeated tokens | a shard is corrupt or mismatched | `python scripts/verify_library.py`; resync the failing file |
| `FAIL` with `3dac4c54…` on the Engram | downloaded from `main`, not the pinned rev | safe; re-fetch at `cb02422c` for reproducibility |
| Verifier says `INCOMPLETE` | download still running | re-run `fetch-library.ps1` (it resumes) |
| Very slow prompt reads at 512K/1M | quadratic indexer | 128K is the practical ceiling; use 1M for one-off demos |
| Model refuses | it is the *censored* rung, or the request is outside its competence | confirm you loaded `…-Uncensored-…` shards |
| `strata` not found after install | PATH not reloaded | new terminal, or `& "$env:LOCALAPPDATA\Strata\terminal\current\bin\strata.cmd"` |
