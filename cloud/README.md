# Lane C — rent the GPU, keep everything else local

The model needs **≥ 12 GiB VRAM** (8 GiB is the floor) and **≥ 48 GiB RAM**, plus ~300 GB of
fast disk for the 2.00 bpw set. If the machine in front of you is a laptop with a 4 GB card,
renting for an hour is the cheapest way to answer "does it actually work, and how fast".

## What to rent

| Instance | Why | Street price |
|---|---|---|
| 1× RTX 4090 24 GB, 64 GB RAM, 200 GB+ NVMe, Ubuntu 22.04/24.04 | sm_89 is in Strata's prebuilt engine; user-measured ~40 tok/s | $0.35–0.60/h |
| 1× RTX 5090 32 GB, 64–96 GB RAM | sm_120, more expert cache, faster | $0.60–1.00/h |
| 1× L40S 48 GB, 96 GB RAM | headroom for 256K context and 8 parallel | $0.80–1.20/h |
| 1× A6000 48 GB, 128 GB RAM | the vendor's own test card | $0.40–0.80/h |

Pick an image with the **NVIDIA driver and CUDA 12.8+ already installed** (the CUDA 12.8
template on RunPod/Vast/Lambda is fine). Do not pick a Windows image: the Linux path is the one
Strata tests with the DeepSeek engine.

Avoid: ≤ 8 GB cards (starts, crawls, may OOM), CPU-only (`strata launch --plan` will refuse),
and anything with a slow SATA disk — the 103 GiB Engram table is read every token.

## Run it

```bash
# on the rented box (copy the whole repo, or just this file + its pins)
bash cloud/provision.sh --check          # hardware verdict, installs nothing
bash cloud/provision.sh --preset balanced
```

The script verifies `install.sh` against the release's `SHA256SUMS.txt`, installs Strata,
downloads the pinned 2.00 bpw set + Engram + drafter, **hashes all seven files** against the
same pins as `manifests/acceptance.json`, then launches and prints the endpoint and key.

```bash
# on your laptop: forward the port, no GPU needed
ssh -N -L 8080:127.0.0.1:8080 user@<host>

# then, locally
python configs/openai_client.py "who are you, in one line"
python Tools/runtime/bench.py --url http://127.0.0.1:8080/v1
strata connect claude-code        # print settings for Claude Code against localhost:8080
```

## Cost sanity check

| Task | Wall clock | Cost at $0.45/h |
|---|---|---|
| 257 GB download on a 1 Gbit host | ~35–40 min | ~$0.30 |
| Model load / pack (first start) | 10–30 min | ~$0.20 |
| A 30-minute working session | — | ~$0.25 |
| **First useful session, all-in** | **~1.5 h** | **≈ $0.70** |

Stop the instance when done: the files live on its volume, and re-launching from a stopped
volume resumes in minutes — but a fresh instance re-downloads.

## Security notes for a rented box

- Bind to `127.0.0.1` (`--access local`, the default) and reach it only through the SSH tunnel.
  `--access lan` mints an API key; `--access cloudflare|tailscale` exposes it further — only
  with a key, and only if you mean it.
- The uncensored model has no built-in refusal layer. Treat the endpoint exactly like a local
  process with your credentials in its environment: anyone who reaches it can use it.
- Wipe the volume when you throw the instance away; the weights are MIT, but the box may also
  hold your prompts and API keys.
