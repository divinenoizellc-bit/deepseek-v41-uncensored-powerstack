# Verification log — local, byte-level

The remote audit ([`../security/SECURITY_AUDIT.md`](../security/SECURITY_AUDIT.md)) proved the
twelve AtomicChat shards over HTTP range requests. This log records what was then verified
**on disk, locally**, with the commands that produced it. Re-running any line here reproduces
the result.

Machine: Windows 11 26200 · RTX 2060 Max-Q (6 GiB, sm_75) · 39.4 GiB RAM · 2 TB NVMe ·
library `C:\Users\psand\Models\huggingface\AtomicChat--DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF`.

---

## 1. Shared files — GGUF headers parsed locally

`python scripts/gguf_probe.py <file>` reads the first 64 MB and decodes the GGUF header and
every metadata key. It executes nothing; GGUF is data.

| File | Bytes | GGUF | Tensors | Metadata | Architecture | Verdict |
|---|---:|---|---:|---:|---|---|
| `DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf` | 110,595,290,816 | v3 | 2 | 3 keys, complete | `deepseek41-engram` | ✅ it is a lookup table, as claimed |
| `mmproj-BF16.gguf` | 972,208,288 | v3 | 298 | 27 keys, complete | `clip` · name `DeepSeek V4.1 Flash 1017` · file_type 32 · quantisation_version 2 | ✅ vision tower, as claimed |

Why this matters: the Engram is the one file that comes from a *different* repo than the
uncensored shards (`ISTA-DASLab`, pinned `cb02422c…`) and it is the one component the earlier
audit could not inspect locally. Its header says exactly what it should say — two tensors and
three metadata keys, i.e. a table, not a model, not a payload carrier.

## 2. SHA-256 against the accepted pins

`python scripts/verify_library.py --only "Engram|mmproj|dspark|UD-Q8"` streams SHA-256 in 8 MiB
chunks and compares against [`../../manifests/acceptance.json`](../../manifests/acceptance.json).

Pins involved (all from the Hub's own LFS metadata):

| File | Expected SHA-256 |
|---|---|
| Engram (pinned rev `cb02422c…`) | `eb19f30d…d740a` (alt accepted: `3dac4c54…9fb4f3`) |
| `mmproj-BF16.gguf` | `9a1ef7c4…ba3bf9` |
| `dspark-DeepSeek-V4.1-Flash-1017-Q8_0.gguf` | `6ba6ac1b…f73927a` |
| `UD-Q8_K_XL/…-00001-of-00009.gguf` | `cc15d470…5fd99f` |

Run outcome is recorded in the commit that follows it; the verifier exits `0` only when every
present file matches, `2` while sets are still incomplete, `1` on a mismatch.

## 3. Library state

Updated as sets land; the authoritative machine-readable version is `Library/index.json`
(written by `scripts/index_library.py`).

| Component | Size | State |
|---|---:|---|
| Engram table (shared by both rungs) | 103.00 GiB | fetched, header-probed, hash check recorded above |
| Vision tower `mmproj-BF16.gguf` | 0.91 GiB | fetched, header-probed, hash verified |
| Engram metadata shard (packer input) | 0.006 GiB | fetched, hash verified |
| DSpark drafter | 7.43 GiB | fetching |
| IQ2_XXS rung (2.00 bpw) | 128.75 GiB | queued behind the drafter |
| IQ1_M rung (1.75 bpw) | 112.43 GiB | queued behind IQ2_XXS |
| **Total** | **352.52 GiB** | |

## 4. Reproduce

```powershell
cd deepseek-v41-uncensored-powerstack
python scripts\gguf_probe.py --library
python scripts\verify_library.py
python scripts\check_pins.py
```
