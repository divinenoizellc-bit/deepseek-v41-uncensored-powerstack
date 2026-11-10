# Provenance — what is in the box and how it got there

Every claim below is checkable against the pinned revisions, without trusting this repository:
`python manifests/build_acceptance.py --check` re-queries the Hub and fails on drift.

## The chain

```
deepseek-ai/DeepSeek-V4.1-Flash-1017                    MIT · 763B params · 384 experts · 1,048,576 ctx
        │  quantization (GSQ-RCO) + the shared Engram table
        ▼
ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF       MIT · rev cb02422c900df489cea5833e8a92171224059b3c
        │  1.75 / 2.00 / 2.25 bpw rungs, 4 shards each, + DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf (103 GiB)
        │  abliteration: refusal direction projected out of the DENSE RESIDUAL WRITERS ONLY
        ▼
AtomicChat/...-Uncensored-GSQ-RCO-GGUF                  MIT · rev 4f1d2f730cff977961db81789e81bfc0d3e6dd2e
        │  IQ2_XXS ✅ pass   IQ1_M ✅ pass   (IQ2_XS ❌ fail — not mirrored)
        │  + drafter / vision tower / metadata shard
        ▼
unsloth/DeepSeek-V4.1-Flash-1017-GGUF                   rev 8a6ec9cf118e785a362ea94ee123c61c70553be6
        │
        ▼
this repository — pins, manifest, audit, packer configs, launcher
```

## What the abliteration actually touched

AtomicChat rebuilt exactly three tensor families, at full precision, with a one-direction
refusal edit (strength 2.0), then quantized them back to ISTA's per-tensor type:

| Tensor | Role |
|---|---|
| `attn_output_b` | attention output projection |
| `ffn_down_shexp` | shared-expert down projection |
| `engram_wkv` | Engram value projection |

The **384 routers / routed experts were left byte-for-byte as ISTA shipped them**, so the
learned low-bit rounding is untouched. That is not a marketing claim; it is the observed file
layout:

- 12 shards, 4 per rung.
- **8 of 12 are bit-identical (same SHA-256) to ISTA's pinned files.**
- The other 4 have **exactly the same byte size** and a different SHA-256 — the fingerprint of
  in-place tensor replacement, not of a repack.
- Parameter count from the GGUF metadata: `551,880,949,208` — matches the Hub API.

The security auditor reproduced this independently, including a `SLACK = 0` check (no room for
appended payloads) and a git-blob-SHA-1 check on every text artifact. Full report:
[`../security/SECURITY_AUDIT.md`](../security/SECURITY_AUDIT.md).

## The Engram file is the odd one out

`DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf` lives in the **ISTA** repo, not the AtomicChat one, and
every rung uses it. Two variants exist under the same name and size:

| Variant | SHA-256 | Where |
|---|---|---|
| 4-shard-layout header (pinned) | `eb19f30d…f298740a` | ISTA @ `cb02422c`, what we pin |
| 6-shard-layout conversion | `3dac4c54…9c9fb4f3` | ISTA @ `main`, after 2026-10-27 |

Both are accepted by Strata (`setup.py: DSV41_SHA_ALSO`) because the table bytes are identical;
only the GGUF header changed (two tensors merged into one, the gate folded). `acceptance.json`
records the pinned hash as primary and the other as an accepted alternate. If the verifier
reports exactly this one file as `FAIL` with the alternate hash, the download came from `main` —
either hash is safe, but re-pin for reproducibility.

## What we deliberately did not mirror

| Excluded | Reason |
|---|---|
| IQ2_XS (2.25 bpw) shards | publisher's own scorecard says `"pass": false`; +145 GiB |
| Unsloth UD-Q8_K_XL (508 GB, 9 shards) | needs several cards + hundreds of GB of RAM |
| ISTA's 6-shard re-split | same weights as the 4-shard layout; we pin the 4-shard one Strata's setup uses |
| ISTA's stock (censored) shards | this project is the uncensored build |

## Reproducing the pin set from scratch

```powershell
python manifests/build_acceptance.py           # rewrite acceptance.json from the Hub
python manifests/build_acceptance.py --check   # fail if anything moved at the pinned revisions
python scripts/check_pins.py                   # same, per repo, with LFS + xet hashes
python scripts/verify_library.py               # stream SHA-256 over the local mirror
```

Sizes and hashes in `acceptance.json` are the Hub's own LFS object ids — not re-typed by hand.
