---
license: mit
base_model:
- ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF
- deepseek-ai/DeepSeek-V4.1-Flash-1017
base_model_relation: quantized
quantized_by: AtomicChat
pipeline_tag: text-generation
library_name: gguf
tags:
- atomic-chat
- deepseek
- deepseek41
- gguf
- gsq
- rco
- strata
- abliteration
- refusal-direction
- uncensored
---

# DeepSeek-V4.1-Flash-1017 Without Refusals · GSQ-RCO
<p style="margin-top: 0; margin-bottom: 0;">
  <em>ISTA-DASLab's GSQ-RCO quantizations of DeepSeek-V4.1-Flash-1017 (763B, 384 experts) with DeepSeek's refusal direction projected
  out of the dense residual writers — the same edit as <a href="https://huggingface.co/AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GGUF">AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GGUF</a>,
  measured on every rung.</em>
</p>

<div style="display: flex; gap: 8px; align-items: center; margin-top: 10px; margin-bottom: 10px;">
  <a href="https://atomic.chat/?utm_source=huggingface&utm_medium=referral&utm_campaign=hf_deepseek_v4_1_flash_1017_uncensored_gsq_rco&utm_content=btn_atomic"><img src="https://huggingface.co/AtomicChat/Qwen3.8-27B-GGUF/resolve/main/btn_atomic.png" width="162" alt="Atomic Chat"></a>
  <a href="https://discord.gg/8wGSsvmg4V"><img src="https://huggingface.co/AtomicChat/Qwen3.8-27B-GGUF/resolve/main/btn_discord.png" width="119" alt="Discord"></a>
  <a href="https://github.com/AtomicBot-ai/Atomic-Chat"><img src="https://huggingface.co/AtomicChat/Qwen3.8-27B-GGUF/resolve/main/btn_github.png" width="115" alt="GitHub"></a>
  <a href="https://x.com/atomic_chat_hq"><img src="https://huggingface.co/AtomicChat/Qwen3.8-27B-GGUF/resolve/main/btn_x.png" width="108" alt="X"></a>
</div>
<ul style="margin: 0 0 12px 0;">
  <li>Built by the team behind <a href="https://atomic.chat/?utm_source=huggingface&utm_medium=referral&utm_campaign=hf_deepseek_v4_1_flash_1017_uncensored_gsq_rco&utm_content=bullet_app">Atomic Chat</a>, the app that runs open-weight models locally and offline.</li>
</ul>
<hr style="margin: 0 0 16px 0;">

- These are [ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF](https://huggingface.co/ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF)'s GSQ-RCO backbone shards (revision `cb02422c900d`)
  with **only the residual-writing dense tensors replaced**: attention output (`attn_output_b`), the shared-expert
  down projection (`ffn_down_shexp`) and the Engram value projection (`engram_wkv`). The **routed experts are left
  exactly as ISTA shipped them**, so GSQ's learned low-bit rounding of the experts is preserved byte for byte, and
  each file stays the same size and runs wherever the original runs.
- The replaced tensors carry the one-direction refusal edit (strength 2.0) baked into DeepSeek's weights at full
  precision and quantized to ISTA's exact per-tensor type.
- Runs on a **single 12 GB GPU** with [Strata](https://github.com/Niko1221/Strata): the backbone sits in system
  memory and the shared **Engram table streams from an SSD**, so a 763B model fits a consumer machine.

> Not every rung cleared every gate; such a rung is published as measured, with its numbers in the table and the metrics repo.

## What changed and what did not

Both files served on Strata, same prompts and template; "→" reads the stock GSQ-RCO rung → this one.

| Rung | bpw | Total GB | JailbreakBench (EN) | XSTest (safe refused) | Thinking high (30) | MMLU (500) | KL to stock |
|---|---|---|---|---|---|---|---|
| `IQ2_XXS` | 2.0 | 249 | 85.2% → **0.0%** | 7.6% → 0.0% | 27/30 → **0/30** | 82.8% (p=0.27) | 0.0225 |
| `IQ2_XS` | 2.25 | 266 | 86.4% → **0.0%** | 4.0% → 0.4% | 27/30 → **2/30** | 81.6% (p=1.00) | 0.0272 |
| `IQ1_M` | 1.75 | 231 | 88.9% → **0.0%** | 4.8% → 0.0% | 27/30 → **1/30** | 80.6% (p=0.75) | 0.0207 |

KL is the edit's distribution shift from the stock rung, from Strata's teacher-forced score mode: a top-64 lower
bound, so the true KL is a little higher. The shift is small enough (KL ~0.02, MMLU-500 within ~1 pt of the stock quant) that the GSQ-RCO quant's task accuracy is preserved — see the reasoning benchmarks below. Measurements, prompts and gates:
[AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GGUF-metrics](https://huggingface.co/datasets/AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GGUF-metrics) (`ablit/gsq/`).

## Reasoning is preserved

The uncensored edit changes only the dense residual writers (attention output, shared-expert FFN-down, Engram value); the 384 GSQ-learned routed-expert layers are left byte-for-byte intact. We benchmarked the edited IQ2_XXS rung against the stock GSQ-RCO quant on the same stand (Strata, reasoning effort 50):

| Benchmark | Stock GSQ-RCO | Uncensored (ours) |
|---|---|---|
| GPQA-Diamond (198 q) | 83.3% | 83.3% |
| AIME25 (30 q) | 76.7% | 80.0% |

GPQA-Diamond is identical and AIME25 is a hair higher (within noise at n=30): abliteration done this way costs no task accuracy. Per-question logs: [metrics repo](https://huggingface.co/datasets/AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GGUF-metrics) (`ablit/gsq/bench/`).

## Running it

Download one rung and ISTA-DASLab's shared Engram file, then serve with Strata:

```bash
hf download AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF --include "*IQ2_XXS*" --local-dir ds-unc
hf download ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF --include "*Engram*" --local-dir ds-unc   # the 110 GB lookup table, once
strata launch --model-path ds-unc/DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00001-of-00004.gguf
```

The Engram file is identical to ISTA-DASLab's and is **not** re-hosted here; keep it on a fast SSD next to the shards.
As of this writing these files run in Strata (DeepSeek-V4.1 with a separate Engram file is not yet in llama.cpp).

## Limitations

- The refusal classifier reads the start of an answer, so a soft refusal later in the text can pass as an answer.
- The edit removes refusals across topics; it does not keep a narrower set of them.
- With thinking on, the edit plans an answer to a request the original declines, and the plan can be long; give such
  requests a larger token budget or a lower effort.

## Responsible use

This model answers requests the original declines. You are responsible for how you use it and for following the laws
that apply to you.

## Credits and license

- Base model: [deepseek-ai/DeepSeek-V4.1-Flash-1017](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017) — MIT (its LICENSE ships here).
- GSQ-RCO quantization and the shared Engram file: [ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF](https://huggingface.co/ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF) (DASLab, IST Austria).
- Runtime: [Strata](https://github.com/Niko1221/Strata).

MIT, as the base model and ISTA-DASLab's GGUFs. Built by AtomicChat.
