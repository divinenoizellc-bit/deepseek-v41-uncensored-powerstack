# POWER.md — running it as hard as it goes

Everything here is measured against two limits that cannot be argued with: **VRAM** (dense
weights + attention cache + expert cache share one pool) and **NVMe bandwidth** (Engram rows and
non-resident experts are read per token). "Overpowered" means spending both deliberately.

Assumes a machine that passes [`HARDWARE.md`](HARDWARE.md): ≥ 12 GB VRAM, ≥ 48 GB RAM, NVMe.

---

## The full-power launch

```powershell
strata launch --family deepseek41 --model ist-das-2.00bpw `
  --context 1m `          # the native maximum; 512k/256k are the honest sweet spots
  --speed full `          # all 6 routed experts per token (--experts 6), not 5
  --parallel 8 `          # 8 concurrent conversations/sessions
  --vision on `           # vision tower; on 24 GB+ VRAM this picks the GPU reader
  --kv int8 `             # int8 KV; q4_0 halves memory again at a small quality cost
  --tune thorough `       # measures DSpark, draft block, CPU threads; keeps >5% wins
  --access local --port 8080 `
  --save-preset nuclear
```

Then, at the API layer, turn the two knobs that are *not* launch flags: reasoning effort and
sampling. Both are per request.

```jsonc
{
  "model": "deepseek-v4.1-flash",
  "messages": [{"role": "user", "content": "..."}],
  "reasoning_effort": "max",          // 1–100, or low/medium/high/max = 50/62/75/100
  "temperature": 0.6,
  "top_p": 0.95,
  "max_tokens": 32768
}
```

`reasoning_effort` is rendered into the prompt as `Reasoning Effort: <n>` in thinking mode.
`"none"` (or `chat_template_kwargs.enable_thinking: false`) turns thinking off entirely — the
fastest path for straightforward extraction tasks.

## Preset matrix

| Preset | Command core | VRAM/RAM appetite | Use it for |
|---|---|---|---|
| `nuclear` | `--context 1m --speed full --parallel 8 --vision on --kv int8 --tune thorough` | maximal; expert cache starved, prompt reads slow (quadratic indexer) | one giant document, batch agent fan-out |
| `balanced` | `--context 128k --speed full --parallel 4 --vision off --kv int8` | sane; experts actually stay cached | daily driver, coding, research |
| `code` | `--context 64k --speed full --parallel 2 --vision off --kv q4_0` | lean; more VRAM for experts | repo-scale coding with Claude Code/Codex |
| `smoke` | `--context 8k --speed faster --parallel 1 --vision off --kv q4_0` | minimum | prove the pack boots before a long run |
| `throughput` | `--context 32k --speed full --parallel 8 --dspark on --drafting dflash2` | high, drafts compete with experts | many short requests/second |

`--speed faster` = 5 of 6 experts; it is the automatic default on ≤16 GB VRAM machines and on
Strix Halo. On a real 24 GB+ card, always start with `--speed full`.

## The memory budget, honestly

At 1M context the attention cache is what eats the expert cache. Vendor measurement on 2×A6000:

| Context | Extra VRAM per extra conversation | What it costs |
|---:|---:|---|
| 8K | ~0.01 GB | nothing measurable |
| 32K | ~0.05 GB | a few experts |
| 128K | ~0.17 GB | a visible slice |
| 512K | ~0.68 GB | real, and prompt reads slow quadratically |

Rule of thumb: **1M context is a demonstration, not a default.** Start at 128K, raise it only
when a specific task needs it, and expect the first reply of a 512K prompt to take minutes.

## Speculative decoding

`--dspark auto` is the vendor default and decides per machine. Where the drafter is a win:

```powershell
strata launch ... --dspark on --dspark-conf 0.65
```

A user report on an RTX 4090 48 GB went from 16–22 tok/s (`auto`) to **40.2 tok/s** (median of
5 × 64-token answers) with `--dspark on --dspark-conf 0.65 --ssd-cache 108`. Do not force
`--dspark off`: the drafter's experts still load and take room without paying for themselves.

## Agentic behaviour: slots and checkpoints

Long agent runs re-read their whole prompt every turn unless the engine keeps the conversation
aside. It does, by default (~17 MB per 6.5K tokens, capped at 2 GB):

| Variable | Default | Effect |
|---|---|---|
| `STRATA_DS4_SLOT_GB` | 2 | total slot budget on disk |
| `STRATA_DS4_SLOT_KEEP` | 1 | `0` disables slot persistence |
| `STRATA_DS4_AUTO_PIN` | 1 | `0` disables system-prompt/tool checkpoint pinning |
| `DS4_ASYNC_T` | engine-sized | verification window; `4` helps small-memory boxes |

## Sampling that does not waste a 551B model

Defaults are `temperature 1.0, top_p 1.0` — fine for chat, wasteful for work.

| Task | temperature | top_p | min_p | notes |
|---|---:|---:|---:|---|
| Code / tool use | 0.2–0.4 | 0.95 | 0.02 | greedy-ish; tool calls want determinism |
| Reasoning / math | 0.6 | 0.95 | 0.0 | thinking already explores |
| Long-form writing | 0.9–1.0 | 0.98 | 0.02 | the model's own default character |
| Extraction / classification | 0.0 | 1.0 | 0.0 | set `reasoning_effort: "none"` too |

## Tool calls

The model emits DeepSeek's DSML (`<｜DSML｜ calls>`, `<｜DSML｜ invoke name=…>`); the server
translates to OpenAI `tool_calls` and Anthropic `tool_use`, including streamed arguments,
`tool_choice`, and calls written inside the thinking block. A parameter marked
`string="true"` stays a string — do not re-parse JSON-looking strings.

## Offload and engine settings (`--set`)

`strata launch --set KEY=VALUE` passes an advanced engine setting or a `STRATA_*` variable
straight through; unknown keys warn instead of refusing, so a typo is visible, not silent.
The ones that matter for a 384-expert model:

| Setting | Example | What it does |
|---|---|---|
| `prefill=<n>` | `--set prefill=65536` | bigger prompt chunks; the vendor writes `8192` on Strix Halo for 11–15% |
| `ssd-cache=<GiB>` | `--set ssd-cache=108` | size of the RAM store for experts (auto-sized by default); a user report used 108 GiB on a 128 GB box |
| `dspark=<word>` | `--set dspark=on` | same as `--dspark`; `dspark-conf=0.65` raised an RTX 4090 from 16–22 to ~40 tok/s |
| `resident-experts` | `--set resident-experts=...` | keep a slice of experts permanently resident (higher memory, lower latency) |
| `kv` | `--kv k8v4` | KV streaming variant; also `int8`, `q4_0`, `fp16` |

Two more levers that are flags, not settings:

- `--pool-cores 2-15:2` pins the CPU workers to named logical processors (one worker per physical
  core by default; two entries on one core warn).
- `--gpu-roles 1=main,0=helper` gives each card a job when there is more than one.

Default expert placement is automatic: as many routed experts as fit in VRAM stay there, the rest
are computed on the CPU from the model files, and whatever RAM cannot hold is read from the SSD.
There is no supported "all experts on CPU" switch — the dense weights are still VRAM-resident, so
VRAM is a gate, not a knob.

## Measure, don't guess

```powershell
python .\Tools\runtime\bench.py --url http://127.0.0.1:8080/v1 --model deepseek-v4.1-flash --runs 5
```

Records decode tok/s, prompt tok/s at 1K/4K/16K, and time-to-first-token. Re-run after every
flag change; the difference between `--speed faster` and `full`, or between `int8` and `q4_0`
KV, is machine-specific.
