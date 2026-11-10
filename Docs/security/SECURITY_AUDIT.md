# Security Audit — `AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF`

**Verdict: CLEAN** — no malicious ware, no code, no obfuscation, no impersonation.
**Confidence: HIGH (≈0.93).**
**Pinned revision:** `4f1d2f730cff977961db81789e81bfc0d3e6dd2e` (this *is* `main`; `sha` from the model API matched, so the audit is not against a stale branch head).
**Audit date:** 2026-11-10 · **Auditor:** sec-auditor · **Method:** HF REST API + token-less `resolve` fetch + HTTP range GGUF parse.
**Blocking findings: NONE.** Two *preconditions* before you run anything (see §13) — one of them is not a repo defect.

---

## 0. Verdict up front

| Question | Answer |
|---|---|
| Does the repo attach a trojan, stealer, dropper, script or binary? | **No.** 16 files: 12 `.gguf`, 1 `.md`, 1 `.json`, `.gitattributes`, `LICENSE`. Nothing else. |
| Is any text artifact a prompt-injection / social-engineering lure? | **No.** Zero `ignore previous`, zero `pip install`, zero encoded blobs, zero invisible/bidi/TAG codepoints, zero `<script>`/`<iframe>`/`onerror=`. |
| Is the publisher who they claim to be? | **Yes.** `AtomicChat` is a **verified** HF org (team plan, 130 models, 66 datasets, 1,390 followers, 148,870 downloads on this repo). |
| Do the two claimed base models exist and match the claim? | **Yes**, both public and MIT. Lineage verifies *byte-for-byte* (§4). |
| Are the weights structurally sound GGUF? | **Yes.** GGUF v3, standard llama.cpp split metadata, `SLACK = 0` on all 12 shards (§5, §6). |
| Is it gated / token-only? | **No.** `gated=false`, `private=false`; all reads returned 200/206 **with no `Authorization` header**. |
| Residual risk | **Low, and it is not the weights** — it is the runtime you must install to execute them (§12). |

**The single most important result in this report:** at the revision the card itself cites, **8 of the 12 shards are byte-identical (same sha256) to ISTA-DASLab upstream**, and the other 4 have **identical sizes** but different hashes — exactly the signature of "edited some tensors in place on top of upstream", which is precisely what the card claims. A repackaging attack cannot produce that pattern.

---

## 1. File census

Established from `https://huggingface.co/api/models/<repo>/tree/4f1d2f7…?recursive=true` **and** `…/tree/main?recursive=true` (both returned 17 identical entries, so `main` == pinned revision).

| # | Path | Bytes | sha256 (first 16) | Ext | Flag |
|---|---|---|---|---|---|
| 1 | `.gitattributes` | 2,671 | `4b24b21dda833345` | .gitattributes | OK |
| 2 | `LICENSE` | 1,084 | `f2c6c602815669d2` | LICENSE | OK |
| 3 | `README.md` | 6,801 | `7830f85bd627771d` | .md | OK |
| 4 | `cards/rungs.json` | 1,297 | `b7804b03f18de8fe` | .json | OK |
| 5 | `…-IQ1_M-00001-of-00004.gguf` | 39,358,830,464 | `6e3f0d5ff53d0042` | .gguf | OK |
| 6 | `…-IQ1_M-00002-of-00004.gguf` | 39,176,113,248 | `34d68c99fdae9948` | .gguf | OK |
| 7 | `…-IQ1_M-00003-of-00004.gguf` | 39,997,334,720 | `fb1dd52e9029400b` | .gguf | OK |
| 8 | `…-IQ1_M-00004-of-00004.gguf` | 2,188,841,824 | `25eb979db1aac9da` | .gguf | OK |
| 9 | `…-IQ2_XS-00001-of-00004.gguf` | 39,535,776,992 | `4c65307992ab586c` | .gguf | OK |
| 10 | `…-IQ2_XS-00002-of-00004.gguf` | 39,494,617,536 | `933461a974fcccee` | .gguf | OK |
| 11 | `…-IQ2_XS-00003-of-00004.gguf` | 39,423,838,496 | `bbf91fa346a85eba` | .gguf | OK |
| 12 | `…-IQ2_XS-00004-of-00004.gguf` | 36,771,591,232 | `18305a5afbf8087e` | .gguf | OK |
| 13 | `…-IQ2_XXS-00001-of-00004.gguf` | 39,075,714,624 | `d46efb67ccffd8fb` | .gguf | OK |
| 14 | `…-IQ2_XXS-00002-of-00004.gguf` | 39,388,449,504 | `cec1b2c3da429dc7` | .gguf | OK |
| 15 | `…-IQ2_XXS-00003-of-00004.gguf` | 39,246,891,616 | `9d9c2140fcb134a0` | .gguf | OK |
| 16 | `…-IQ2_XXS-00004-of-00004.gguf` | 20,527,837,312 | `92e1b7aac2c27451` | .gguf | OK |

**Counts by type:** `.gguf` 12 · `.md` 1 · `.json` 1 · `.gitattributes` 1 · `LICENSE` 1 · **directories: 1** (`cards`).
**Files not of an allowed type: 0.** No `*.py`, `*.pkl`, `*.bin`, `*.pt`, `*.pth`, `*.exe`, `*.dll`, `*.js`, `*.sh`, `*.whl`, `*.zip`, no `.gitmodules`, no `*.safetensors`.

**Storage accounting cross-check:** the model API reports `usedStorage = 414,185,837,568`, which equals the sum of the 12 visible shards **exactly** (414,185,837,568 B). A hidden large blob would break this identity. It does not.

**Totals:** 12 shards ≈ **414.19 GB** (414,185,837,568 B) + 11,853 B of text. Per set: IQ1_M 120.72 GB, IQ2_XS 155.23 GB, IQ2_XXS 138.24 GB.

---

## 2. Text-artifact audit (all four fetched at the pinned revision, token-less)

Integrity of each artifact was proven *before* reading it: I recomputed the **git blob SHA-1** of the served bytes and compared it to the `oid` in the pinned tree — **4/4 matched**:

| Artifact | served sha256 | git blob SHA-1 recomputed | tree `oid` | match |
|---|---|---|---|---|
| `README.md` | `7830f85b…` | `160420a94d06802dbf0131c63aefba276cdf0b06` | `160420a94d06…` | ✅ |
| `LICENSE` | `f2c6c602…` | `d62e3bef9f054f21b7fc616365850fbf879a99ff` | `d62e3bef9f05…` | ✅ |
| `cards/rungs.json` | `b7804b03…` | `23f96d807b81f811307ba1af82e0fbff23c7482f` | `23f96d807b81…` | ✅ |
| `.gitattributes` | `4b24b21d…` | `b1e3ec093cff28e4f17fb6750292330a853d0462` | `b1e3ec093cff…` | ✅ |

### 2.1 Injection / obfuscation scan — all negative

| Probe | README | LICENSE | rungs.json | .gitattributes |
|---|---|---|---|---|
| `ignore (all) previous/prior …` | 0 | 0 | 0 | 0 |
| `pip install` / `npm i` / `run this` / `execute this` | 0 | 0 | 0 | 0 |
| `powershell` / `cmd.exe` / `curl ` / `wget ` / `reg add` / `schtasks` / `Set-MpPreference` | 0 | 0 | 0 | 0 |
| `disable (antivirus\|defender\|firewall)` / `add exclusion` | 0 | 0 | 0 | 0 |
| `<script` / `<iframe` / `onerror=` / `onload=` / `javascript:` / `<object` / `<embed` | 0 | 0 | 0 | 0 |
| base64 blobs (≥80 chars decoding to printable data) | 0 | 0 | 0 | 0 |
| long hex blobs (≥64 hex octets) | 0 | 0 | 0 | 0 |
| zero-width (U+200B/C/D, U+FEFF, U+2060, U+180E) | 0 | 0 | 0 | 0 |
| bidi overrides (U+202A–202E, U+2066–2069) | 0 | 0 | 0 | 0 |
| Unicode TAG chars (U+E0000–E007F, the classic hidden-instruction channel) | 0 | 0 | 0 | 0 |
| other `Cf/Co/Cs` control chars | 0 | 0 | 0 | 0 |

Non-ASCII in `README.md` is **15 code points**, all ordinary typography (`→`, `·`). There is **no** hidden text, no `display:none`, no `font-size:0`, no HTML comment trick.

The only keyword hit in the entire corpus is the literal benchmark name **"JailbreakBench"** in the README results table — a dataset name, not an instruction. Quoted in context:

```text
| Rung | bpw | Total GB | JailbreakBench (EN) | XSTest (safe refused) | Thinking high (30) | MMLU (500) | KL to stock |
| `IQ2_XXS` | 2.0 | 249 | 85.2% → **0.0%** | 7.6% → 0.0% | 27/30 → **0/30** | 82.8% (p=0.27) | 0.0225 |
```

The HTML in the README is limited to presentation tags `<p> <em> <a> <div> <img> <ul> <li> <hr>` used for badge images. Every `href`/`src` is an https URL to `atomic.chat`, `discord.gg`, `github.com`, `x.com`, or `huggingface.co`. No `javascript:` URI, no `data:` URI, no inline event handler.

### 2.2 What the card actually tells you to do (read as *data*, verbatim)

```bash
hf download AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF --include "*IQ2_XXS*" --local-dir ds-unc
hf download ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF --include "*Engram*" --local-dir ds-unc   # the 110 GB lookup table, once
strata launch --model-path ds-unc/DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00001-of-00004.gguf
```

This is the **only** operationally dangerous content in the repo, and it is dangerous for a boring reason: it asks you to install a third-party inference runtime (`strata`, from `github.com/Niko1221/Strata`). It is not an injection — it is a documented dependency. It is analysed in `THIRD_PARTY_BINARIES.md`.

### 2.3 Card ↔ `rungs.json` internal consistency

The two artifacts agree, digit for digit: IQ2_XXS `refusal_en` 0.8518… ↔ "85.2%", `xstest` 0.076 ↔ "7.6%", `think_high` 27 → 0, `mmlu` 0.828 ↔ "82.8%", `kl_to_stock` 0.0225; IQ2_XS `pass: false` ↔ the card's own disclaimer *"Not every rung cleared every gate; such a rung is published as measured"*. Fiction is cheap; consistent fiction across two files plus a third public dataset (§3.3) is not.

---

## 3. Provenance & legitimacy

### 3.1 Base models — both real, public, MIT

| Field | `deepseek-ai/DeepSeek-V4.1-Flash-1017` | `ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF` |
|---|---|---|
| HTTP | 200 | 200 |
| private / gated | false / false | false / false |
| license | mit | mit |
| created | 2026-10-17T02:40:38Z | 2026-10-23T09:43:05Z |
| downloads / likes | 329,529 / 5,468 | 3,398,732 / 651 |
| tags of interest | `deepseek_v41`, `safetensors`, `8-bit`, `fp8` | `gguf`, `gsq`, `rco`, `arxiv:2604.18556`, `arxiv:2605.00649` |
| params | `safetensors.total = 763,205,315,794` | — |
| storage | 510.75 GB | 1,287.45 GB |

The card's *"763B, 384 experts"* matches the base model's **763,205,315,794** params, and `384` matches `deepseek41.expert_count` in the GGUF metadata (§7). The claimed lineage is `deepseek-ai → ISTA-DASLab GSQ-RCO quant → AtomicChat abliterated re-pack`, and every link exists.

### 3.2 Publisher

`AtomicChat` — HF **organization**, not a throwaway user account: `isVerified: true`, `plan: team`, `numUsers: 6`, `numModels: 130`, `numDatasets: 66`, `numFollowers: 1390`. `GET /api/users/AtomicChat` returns 404 precisely *because* it is an org (expected, not an anomaly). `GET /api/organizations/AtomicChat/overview` returns 200 with the above.

Repo facts: `createdAt 2026-10-28T04:48:45Z`, `lastModified 2026-10-31T07:29:05Z`, `downloads 148,870`, `likes 424`, `library_name gguf`, `pipeline_tag text-generation`.

### 3.3 Every claim the card makes was independently resolved

| Card claim | Verification | Result |
|---|---|---|
| ISTA shards at revision `cb02422c900d` | `…/revision/cb02422c900d` | **HTTP 200**, exists, MIT |
| "110 GB lookup table" | `DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf` = **110,595,290,816 B** (110.6 GB) | ✅ |
| "not re-hosted here" | this repo's tree contains no `*Engram*` file | ✅ |
| metrics at `ablit/gsq/` | dataset tree contains `ablit/gsq/{IQ1_M,IQ2_XS,IQ2_XXS}/{ours,stock}/` | ✅ |
| per-question logs at `ablit/gsq/bench/` | `ablit/gsq/bench/{stock,ours}/{gpqa_diamond,aime25}.json{,l}` | ✅ |
| sibling repo `…-Uncensored-GGUF` (llama.cpp version) | HTTP 200, 13,322 dl, `llama.cpp`/`imatrix` tags | ✅ |
| MIT license | LICENSE text is MIT, `cardData.license = mit`, `general.license = mit` (in GGUF) | ✅ |

The referenced metrics dataset is a **160-file** evidence tree containing refusal probes, MMLU logs, KL lines, and stratified screens — considerably more detail than a lure would bother to fabricate.

---

## 4. Upstream parity — the strongest single signal

Compared against `ISTA-DASLab/…-GSQ-RCO-GGUF` **at the revision the card cites (`cb02422c900d`)**:

| Shard | Ours (B) | ISTA (B) | Size equal | sha256 equal |
|---|---|---|---|---|
| IQ1_M-00001 | 39,358,830,464 | 39,358,830,464 | ✅ | **✅ identical** |
| IQ1_M-00002 | 39,176,113,248 | 39,176,113,248 | ✅ | **✅ identical** |
| IQ1_M-00003 | 39,997,334,720 | 39,997,334,720 | ✅ | ❌ modified |
| IQ1_M-00004 | 2,188,841,824 | 2,188,841,824 | ✅ | ❌ modified |
| IQ2_XS-00001 | 39,535,776,992 | 39,535,776,992 | ✅ | **✅ identical** |
| IQ2_XS-00002 | 39,494,617,536 | 39,494,617,536 | ✅ | **✅ identical** |
| IQ2_XS-00003 | 39,423,838,496 | 39,423,838,496 | ✅ | **✅ identical** |
| IQ2_XS-00004 | 36,771,591,232 | 36,771,591,232 | ✅ | ❌ modified |
| IQ2_XXS-00001 | 39,075,714,624 | 39,075,714,624 | ✅ | **✅ identical** |
| IQ2_XXS-00002 | 39,388,449,504 | 39,388,449,504 | ✅ | **✅ identical** |
| IQ2_XXS-00003 | 39,246,891,616 | 39,246,891,616 | ✅ | **✅ identical** |
| IQ2_XXS-00004 | 20,527,837,312 | 20,527,837,312 | ✅ | ❌ modified |

**8/12 byte-identical. 12/12 size-identical. 4 modified, and those 4 are exactly the shards holding the dense tensors** (`attn_output_b`, `attn_kv`, `attn_q_a_norm`, `hc_attn_*`, `ffn_*_shexp`, `ffn_norm`, `engram_*`) while the shards holding *only routed experts* (`ffn_{gate,down,up}_exps`) are bit-identical. That is a mechanical confirmation of the card's central claim: *"only the residual-writing dense tensors [were] replaced … the routed experts are left exactly as ISTA shipped them"* and *"each file stays the same size"*.

> ⚠️ **Trap for future re-verification:** ISTA's **current `main`** has been **re-sharded to `of-00006`** (first shard is a 5.8 MB metadata header, sizes all differ). Verifying against `main` instead of `cb02422c900d` produces a *false mismatch*. Pin the revision.

---

## 5. GGUF header evidence (per shard, first 2 MiB + bounded metadata completion)

All 12 shards returned **HTTP 206** with `Range: bytes=0-2097151` and no auth token. Magic `GGUF` at offset 0 in 12/12; version `3` (LE uint32) in 12/12.

| Shard | n_tensors | n_kv | `general.file_type` | `split.no` | `split.count` | `split.tensors.count` | tensor types observed |
|---|---|---|---|---|---|---|---|
| IQ1_M-00001 | 46 | 81 | 31 | 0 | 4 | 1008 | IQ1_S×34, IQ2_XXS×5, IQ1_M×2, IQ2_S×1, I32, I64×3 |
| IQ1_M-00002 | 41 | 3 | — | 1 | 4 | 1008 | IQ1_S×28, IQ1_M×6, IQ2_XXS×6, IQ2_S×1 |
| IQ1_M-00003 | 647 | 3 | — | 2 | 4 | 1008 | Q5_K×168, F32×337, Q8_0×56, BF16×49, IQ1_*×37 |
| IQ1_M-00004 | 274 | 3 | — | 3 | 4 | 1008 | Q5_K×76, F32×152, BF16×22, Q8_0×24 |
| IQ2_XS-00001 | 37 | 81 | 20 | 0 | 4 | 1008 | IQ2_XXS×28, IQ2_XS×3, IQ2_S×2, I32, I64×3 |
| IQ2_XS-00002 | 32 | 3 | — | 1 | 4 | 1008 | IQ2_XXS×21, IQ2_XS×7, IQ2_S×4 |
| IQ2_XS-00003 | 30 | 3 | — | 2 | 4 | 1008 | IQ2_XS×13, IQ2_XXS×9, IQ2_S×7, IQ3_XXS×1 |
| IQ2_XS-00004 | 909 | 3 | — | 3 | 4 | 1008 | F32×489, Q5_K×244, Q8_0×80, BF16×71, IQ2_*×25 |
| IQ2_XXS-00001 | 42 | 81 | 19 | 0 | 4 | 1008 | IQ1_M×30, IQ2_XXS×8, I32, I64×3 |
| IQ2_XXS-00002 | 36 | 3 | — | 1 | 4 | 1008 | IQ1_M×19, IQ2_XXS×12, IQ2_XS×5 |
| IQ2_XXS-00003 | 34 | 3 | — | 2 | 4 | 1008 | IQ2_XXS×17, IQ1_M×9, IQ2_XS×8 |
| IQ2_XXS-00004 | 896 | 3 | — | 3 | 4 | 1008 | F32×489, Q5_K×244, Q8_0×80, BF16×71, IQ2_*×12 |

Everything here is textbook llama.cpp behaviour:

* **Only shard 1 of each set carries the 81 full metadata keys** (architecture, tokenizer, template). Shards 2–4 carry exactly `{split.no, split.count, split.tensors.count}`. That is precisely what `gguf-split` writes; a hand-rolled or re-wrapped container would almost certainly duplicate metadata or invent keys.
* `general.file_type` = **19 / 20 / 31**, which are `MOSTLY_IQ2_XXS` / `MOSTLY_IQ2_XS` / `MOSTLY_IQ1_M` in llama.cpp's `llama_ftype` enum — each matching its own filename. (Raw integers given because the enum has grown across versions; the *declared* label and the *observed* dominant tensor type agree in all three sets. Note IQ1_M is genuinely mixed-precision — that is GSQ-RCO's design, documented in ISTA's `tensor-allocation/*.rco-allocation.txt`.)
* `split.tensors.count = 1008` in every shard, and the **actual sum of per-shard `n_tensors` is 1008 in all three sets** (46+41+647+274; 37+32+30+909; 42+36+34+896). Internal consistency at the arithmetic level.
* Tensor names are the real architecture: `blk.{0..39}.ffn_{gate,up,down}_exps` (384-expert MoE), `attn_q_a_norm`, `attn_kv_a_norm`, `attn_sinks`, `attn_output_{a,b}`, `hc_attn_{base,fn,scale}`, `hyper_connection.*`, `engram_{token_map,primes,offsets,multipliers}`. Nothing exotic, nothing executable.

### 5.1 Embedded-executable scan (2 MiB prefix, every shard)

| Signature | Hits |
|---|---|
| `PE\0\0` (Windows executable) | **0 in all 12** |
| `\x7fELF` (Linux executable) | **0 in all 12** |
| `PK\x03\x04` (ZIP/archive) | **0 in all 12** |
| `MZ` (2-byte DOS header prefix) | 5+ per shard *in shards 2–4* — **benign, see below** |
| `#!/` and `<script` | 1 each *in shard 1 of each set* — **benign, see below** |

Both "hits" are false positives, and I verified rather than assumed:

* **`#!/` and `<script`** occur inside `tokenizer.ggml.tokens`, the **129,280-entry BPE vocabulary**. The raw bytes show length-prefixed standalone tokens: `…rapy`, `<script`, `aura`, `illin` — i.e. the words `#!/` and `<script` are *vocabulary entries* (a code-capable tokenizer must contain them). A 2 MiB window of a 40 GB file whose only "script" string sits between `rapy` and `aura` is not a payload.
* **`MZ`** is a **2-byte** pattern; in 2 MiB of high-entropy quantized weights, ~32 occurrences are *expected* by chance (2²¹/2¹⁶). Crucially there is **no `PE\0\0` anywhere** and **`GGUF` occupies offset 0**, so no `MZ` can begin a file. The hits sit inside tensor-name strings (`…weight`, `MZa`, `blk.4.hc_attn_base.weight`). This is noise, not a dropper.

---

## 6. Structural integrity — `SLACK = 0` on 12/12

For each shard I computed, from the parsed tensor table:
`data_start = align_up(end_of_tensor_infos, 32)` and `max_tensor_end = max(tensor.offset + tensor.byte_size)`, then compared against the file's declared size.

| Shard | declared size | data_start | max tensor end | **slack** |
|---|---|---|---|---|
| IQ1_M-00001 | 39,358,830,464 | 5,255,232 | 39,353,575,232 | **0** |
| IQ1_M-00002 | 39,176,113,248 | 3,168 | 39,176,110,080 | **0** |
| IQ1_M-00003 | 39,997,334,720 | 40,384 | 39,997,294,336 | **0** |
| IQ1_M-00004 | 2,188,841,824 | 16,992 | 2,188,824,832 | **0** |
| IQ2_XS-00001 | 39,535,776,992 | 5,254,560 | 39,530,522,432 | **0** |
| IQ2_XS-00002 | 39,494,617,536 | 2,496 | 39,494,615,040 | **0** |
| IQ2_XS-00003 | 39,423,838,496 | 2,336 | 39,423,836,160 | **0** |
| IQ2_XS-00004 | 36,771,591,232 | 56,384 | 36,771,534,848 | **0** |
| IQ2_XXS-00001 | 39,075,714,624 | 5,254,912 | 39,070,459,712 | **0** |
| IQ2_XXS-00002 | 39,388,449,504 | 2,784 | 39,388,446,720 | **0** |
| IQ2_XXS-00003 | 39,246,891,616 | 2,656 | 39,246,888,960 | **0** |
| IQ2_XXS-00004 | 20,527,837,312 | 55,424 | 20,527,781,888 | **0** |

**Every byte of all 12 files is accounted for by header + metadata + declared tensors.** There is no appended archive, no trailing overlay, no gap, no pre-allocated slack region. This is the check that would catch a "GGUF + appended payload" attack, and it is exactly zero. Unknown tensor types: 0. Tensor count mismatch: 0.

### 6.1 Arithmetic reconciliation of the card's numbers

Summing `prod(dims)` over each set's 1008 tensors: **551,880,949,208 params per set — identical across all three sets**, which is the API's *"551.88B params"* to the digit. The base model has 763,205,315,794. Difference ≈ **211.3B params**, consistent with the **external 110.6 GB Engram table** (~4.2 bpw) that is deliberately *not* in these files.

The README's `Total GB` column then reconciles too:

| Rung | shards + 110.6 GB Engram | README says |
|---|---|---|
| IQ1_M | 231.3 GB | **231** |
| IQ2_XS | 265.8 GB | **266** |
| IQ2_XXS | 248.8 GB | **249** |

Three independent numbers (shard sizes, param count, table column) tie out. Fabricated marketing copy does not usually survive arithmetic.

---

## 7. Complete metadata inventory (81 KV, shard 1)

Prefixes: `general.*`, `deepseek41.*` (arch metadata), `tokenizer.ggml.*`, `split.*`, plus `quantize.imatrix.entries_count` / `quantize.imatrix.chunks_count` — the last two are written by `llama-quantize --imatrix`, i.e. standard toolchain output.

Notably **absent**: `general.description`, `general.author`, `general.source.url`, `general.url`, `general.notes`, `general.version`. No free-text fields that a UI might render as instructions. `general.alignment` is absent (default 32), which is consistent with `data_start` alignment I computed.

Standard/high-value values: `general.architecture=deepseek41`, `general.type=model`, `general.size_label=384x212B`, `general.license=mit`, `general.quantized_by="ISTA DASLab"`, `general.name="DeepSeek-V4.1-Flash-1017 GSQ-RCO IQ2_XXS"`, `general.quantization_version=2`, `block_count=40`, `context_length=1048576`, `embedding_length=5120`, `attention.head_count=64`, `head_count_kv=1`, `key_length=512`, `expert_count=384`, `expert_used_count=6`, `rope.scaling.type=yarn`, `rope.scaling.factor=16.0`, `engram.present=true`, `engram_vocab_size=16000000`, `tokenizer.ggml.model=gpt2`, `tokenizer.ggml.pre=joyai-llm`, `bos=0`, `eos=1`, `add_bos=false`, `add_eos=false`.

**`general.quantized_by = "ISTA DASLab"` is a mild but honest divergence** from the HF card (`quantized_by: AtomicChat`): the *file* correctly still credits ISTA as the quantizer, because AtomicChat only replaced tensor groups on top of ISTA's quant. Consistent with §4, not with impersonation.

### 7.1 `tokenizer.chat_template` — inspected in full

7,387 chars, 118 Jinja statements, 27 expressions. It is a normal DeepSeek-family template: `｜System｜`/`｜User｜`/`｜Assistant｜` framing, `<think>`/`</think>`, `Reasoning Effort: N (1-100)` prefix, `｜DSML｜` tool-call rendering with JSON-schema injection, `raise_exception` bounds-check on `reasoning_effort`, and `from_json`/`tojson` filters.

Scanned for dangerous constructs: **no `<script`, no `javascript:`, no `http(s)://`, no `import`, no `exec(`, no `eval(`, no `os.`, no `subprocess`, no `__class__`/attribute-escape, no "ignore previous", no "you are now"**. The only matches were `tool_call` ×10 (the tool-rendering feature itself).

The template *can* reshape the prompt — that is its function, and it is the one place in a GGUF where text is trusted — but it cannot execute code or reach the network through llama.cpp's Jinja evaluation.

### 7.2 Concrete finding: the external Engram pointer is **not verifiable**

```text
deepseek41.engram.present = true
deepseek41.engram.file    = "DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf"
deepseek41.engram.source  = "1bae0e1088993b9b82de08f59de5be5a34e42170"
```

`1bae0e10…` **does not resolve** as a revision of the ISTA repo (**HTTP 404**). So the single most important external dependency — 110.6 GB that must be loaded alongside the model — is referenced only by an opaque 40-hex string that a client cannot check. There is **no embedded sha256** for it. Consequence: the mirror must pin that file out-of-band (hash recorded in §13 and in `manifests/repo.json`), because a runtime that "just downloads the Engram file" has nothing to verify it against.

---

## 8. Typosquat / impersonation sweep

`?search=` over `DeepSeek-V4.1-Flash-1017`, `-Uncensored`, `AtomicChat`, `Atomic-Chat`, `Atomic Chat`, `AtomicChatGGUF`, `AtomiChat` (100 results per query).

**No impersonation of the publisher exists.** Every `atomic`-named model resolves to the real `AtomicChat` org (100+ repos) except three unrelated accounts (`Atomic-Ai/GPT-Chat-German*`, `atomiCode/peft_llama_chatbot*` — 16/9/5 downloads, different product entirely). No `AtomicChatt`, no `Atomic-Chat` org, no lookalike verified badge.

**The real-name family is crowded but non-hostile.** 70+ derivatives exist (`unsloth/…-GGUF` 1.2M dl, `huihui-ai/…-abliterated`, `nvidia/…-NVFP4`, `dealignai/…-UNCENSORED-FP8`, …) — this is a *popular* model family, which is itself mild evidence of legitimacy: the target sits at the top of the family by downloads (148,870) with 424 likes.

Two name-adjacent repos deserve explicit classification:

| Repo | Relation | Verdict |
|---|---|---|
| `dineshr93/DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF` | **Identical repo name, different author.** Created 2026-11-03 (6 days after ours), 1,529 dl, 3 likes. Its card **honestly declares** `base_model: [deepseek-ai/…, AtomicChat/…-Uncensored-GGUF]`, uses `of-00006` shards matching ISTA `main`, and targets one AMD Strix Halo box via a `gufo` fork. | **Derivative, not a lure.** Honest attribution. But it is the single easiest way to fetch the *wrong* bytes — `--include` patterns and casual `hf download` copy-paste will hit it. Pin the full `AtomicChat/…` id. |
| `Abiray/…-Uncensored-GSQ-RCO-IQ2_XXS-GGUF` | 497k dl, declares `base_model: ISTA-DASLab/…` honestly. | **Derivative.** Not an impersonation of this repo. |

Note for the record: `dineshr93` ships a `convert_ds41_upstream.py`; **our** repo ships no `.py` at all.

---

## 9. License & redistribution

* `LICENSE` = verbatim MIT, `Copyright (c) 2023 DeepSeek`. **No redistribution limits, no field-of-use clause, no additional terms.**
* `cardData.license = "mit"`, YAML `license: mit`, GGUF `general.license = "mit"` — **four-way consistent**.
* Base model is MIT, ISTA quants are MIT, so an MIT re-license of a modified derivative is coherent.
* The card's own "Responsible use" note is a request, not a license restriction: *"This model answers requests the original declines. You are responsible for how you use it and for following the laws that apply to you."* MIT governs redistribution; export-control/local-law obligations are yours regardless.
* **Caveat that is not a license issue:** the weights are deliberately *abliterated* (refusal direction projected out at strength 2.0). If your use case assumes a model that refuses harmful requests, this artifact invalidates that assumption by design. `JailbreakBench` refusal drops 85–89% → **0.0%**, measured and published.

---

## 10. Supply-chain hygiene

| Check | Result |
|---|---|
| `.gitattributes` content | Stock HF LFS template (35 generic rules) **plus 12 explicit** `…-of-00004.gguf filter=lfs diff=lfs merge=lfs -text` lines — one per shard. No `filter=` pointing anywhere unusual, no `smudge`/`clean` command, no `!`-negation trick. |
| LFS pointer tricks | Shards: `lfs.pointerSize = 136` on all 12 (normal pointer); text files are **not** LFS (absent from `lfs`, served directly). No shard is itself a pointer to another repo. |
| Submodules | No `.gitmodules`; the only directory in the tree is `cards`. |
| `trust_remote_code` | **Not applicable and not required.** GGUF is a data container; `library_name: gguf`, no `.py`, no `custom_code` tag, transformers is not in the path. |
| Hidden/custom code | None. 0 code files of any language. |
| `hf_xet` required? | **No.** HF serves these through Xet, but plain HTTPS range requests work with no special client, no token. |
| Gated? | **No** (`gated: false`). All 4 text fetches and all 13 range requests returned 200/206 with **no `Authorization` header**. |
| ⚠️ Hash-naming trap | The `ETag` on `resolve` is the **`xetHash`**, **not** the LFS sha256 (`3201921c…` vs `d46efb67…` for IQ2_XXS-00001 — different values). Verify mirrors against `lfs.oid` / `SHA256SUMS`, never against `ETag`. |

---

## 11. Attack-surface model — what a GGUF *could* still do

Weights execute no code. But a GGUF is a parsed container, so the residual surface is real and worth naming precisely:

| Vector | Mechanism | Status here | Why the residual risk is low |
|---|---|---|---|
| **Parser RCE** | Every length/count field is attacker-controlled: KV string `u64` length, array `u64` count, `n_dims`, per-dim `u64`, tensor count. A memory-safety bug in a C++ reader can be driven to integer-overflow → heap overflow. | Parsed cleanly: 81 KV, string lengths ≤ 1,289,455 B (a legitimate token array), array counts ≤ 129,280, `n_dims` ≤ 2, no absurd values, zero unknown types. | Values sit inside the range llama.cpp itself emits; there is no "crafted" outlier to exploit. A malicious file would still need a *buggy* runtime — i.e. the risk lives in the runtime, not this repo. |
| **Metadata/template injection** | `tokenizer.chat_template` is Jinja evaluated at request time; can inject a hidden system prompt or force tool-call JSON. | Fully inspected (§7.1): 7,387 chars, no network/import/eval, standard DeepSeek template. | Template can steer *the model's text*, not the host. It cannot read files or open sockets through llama.cpp's filters. |
| **Provenance spoofing** | `general.*` strings are self-asserted and unauthenticated. | `quantized_by=ISTA DASLab` vs card's `AtomicChat` — a benign, explainable divergence (§7). | Authenticity here comes from content hashes + upstream bit-parity (§4), **not** from self-asserted strings. |
| **Load-time DoS** | Huge `context_length`, absurd `expert_count`, giant KV arrays → memory exhaustion or minute-long allocs. | `ctx=1,048,576`, `384` experts, 1.29 MB token array — all consistent with the *real* model size; `slack=0` means allocated bytes = tensor bytes. | No amplification: file size and declared tensors match to the byte. |
| **Appended payload / steganography** | Concatenate `GGUF + <archive>`; or hide bits inside quantized weights. | **Appended data: impossible** — `slack = 0` on 12/12 (§6). **Inside weights: not excluded** — I did not decode 414 GB. | Any hidden payload would have to live in the **4 modified shards** — but 8/12 are *bit-identical* to upstream, and the 4 that differ are the ones the card openly says were edited, in the tensor groups it names. An attacker gains nothing by hiding in the one place that is disclosed and diffable. |
| **Model behaviour** | The artifact is a model that complies with requests the base refuses. Prompt-triggered harmful *output* is the product, not a payload. | Measured by the publisher (refusal 85–89% → 0.0%). | This is a **policy/legal/dual-use** risk you accept knowingly, categorically different from malware. Named in §12.2. |

**Bottom line:** the weights are inert data; every integrity property that *can* be checked without full decode checks out, and the residual risk collapses onto the runtime you choose to parse them.

---

## 12. Residual risks (ranked)

### 12.1 — **Highest: the runtime, not the repo.** 
To run this you must install a third-party inference engine. The card points at `github.com/Niko1221/Strata`, whose `setup.py` is an **11,256-line, 713 KB one-click network installer** that fetches Python, downloads tensors, and starts a server on `127.0.0.1:8080`. That is a far larger and far less auditable execution surface than the weights, and it is **not signed**. Separately, llama.cpp's Windows nightlies are **unsigned zips** built by `github-actions[bot]`. Details, hashes and the safest acquisition path are in [`THIRD_PARTY_BINARIES.md`](THIRD_PARTY_BINARIES.md).

### 12.2 — Safety/dual-use (not malware)
An abliterated 763B MoE with refusals removed is a capability, not a compromise. `JailbreakBench` goes to 0.0% by construction. If anything downstream assumed refusal behaviour, that assumption is void. Treat outputs accordingly; MIT does not transfer liability.

### 12.3 — Unpinned external dependency
The required 110.6 GB `DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf` is referenced by `deepseek41.engram.source = 1bae0e10…`, which **404s** as an ISTA revision, and no sha256 is embedded (§7.2). Pin it by hash: `eb19f30d368d393784e1fc54fdfaffc427ebb2110bf3762fdf5a8fbb9a2d740a` (110,595,290,816 B, ISTA `@cb02422c900d`). A runtime that fetches it unverified is the one place a substitution attack is cheap.

### 12.4 — Not-all-bytes-inspected
I read ≤8 MiB per shard plus full tensor tables; I did not download 414 GB, so I cannot sign off on the *values* of every quantized block. Mitigated by `slack=0`, 8/12 upstream bit-parity, and standard metadata — but it is an honest limit, not a proof of benign tensor content.

### 12.5 — Name-adjacent fetch hazard
`dineshr93/…` is an exact-name repo by a different author (§8). Copy-pasted `hf download` commands with a truncated id will fetch different, unvetted bytes. Always use the full `AtomicChat/…` id **and** the pinned revision.

### 12.6 — Upstream drift
ISTA `main` is now `of-00006`; the card cites `cb02422c900d` (`of-00004`). Re-verify against the cited revision or you will manufacture a false alarm.

---

## 13. Preconditions before installation (not blockers)

1. **Mirror completeness:** the 12 shards are **not runnable alone** — you also need the 110.6 GB Engram file from a *different* repo/revision. Mirror total = **524,781,128,384 B (524.78 GB)**. Pin the Engram by the sha256 in §12.3.
2. **Do not run the Strata installer unvetted.** Prefer a signed runtime (Ollama, Authenticode-valid) or llama.cpp with a digest-checked archive. See `THIRD_PARTY_BINARIES.md`.
3. Verify every shard against `manifests/SHA256SUMS` **after** transfer, then confirm each file's first 4 bytes are `GGUF` and its size matches `manifests/repo.json`.

---

## 14. Re-audit triggers

* `sha` of the repo changes (any commit — this audit is bound to `4f1d2f7…`).
* Any new file appears, or the file count leaves 16.
* The Engram file's sha256 changes.
* `README.md` / `cards/rungs.json` content changes (hash change is sufficient).
* You switch runtimes (the surface moves entirely).

---

## Appendix A — Reproduction

```powershell
# census (no token)
curl.exe -sS "https://huggingface.co/api/models/AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF/tree/4f1d2f730cff977961db81789e81bfc0d3e6dd2e?recursive=true"

# text artifacts at the pinned revision (no token) — then verify git blob sha1 == tree oid
curl.exe -sS -o README.md "https://huggingface.co/AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF/resolve/4f1d2f730cff977961db81789e81bfc0d3e6dd2e/README.md"

# GGUF magic + header, range only (no full shard)
curl.exe -sS -r 0-2097151 -o head.bin "https://huggingface.co/AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF/resolve/4f1d2f730cff977961db81789e81bfc0d3e6dd2e/DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00001-of-00004.gguf"
# first 4 bytes => 47 47 55 46 ("GGUF"), then LE uint32 version = 03 00 00 00
```

## Appendix B — Evidence retained (`%TEMP%\secaudit`)

`tree_main.json`, `tree_rev.json`, `model_info.json`, `textfiles.json`, `textscan.json`, `provenance.json`, `ista_tree.json`, `ista_tree_rev.json`, `gguf_audit.json`, `gguf_deep.json`, `gguf_structure.json`, plus the four fetched text artifacts and the 6 audit scripts. Nothing outside `Docs\security\` and `manifests\` was written; no binary was installed or executed; no full shard was downloaded (max 8 MiB per shard, range requests only).
