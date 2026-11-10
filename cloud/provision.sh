#!/usr/bin/env bash
# provision.sh - bring up DeepSeek-V4.1-Flash-1017 (uncensored, 2.00 bpw) on a rented
# Linux GPU box, verified end to end, then print how to reach it from your laptop.
#
#   curl -fsSL <this file> | bash -s -- --preset balanced
#   bash provision.sh --check           # hardware verdict only, installs nothing
#   bash provision.sh --stop            # stop the server
#
# Target images: RunPod / Vast.ai / Lambda "Ubuntu 22.04 or 24.04 + CUDA 12.8+" templates.
# Requires: NVIDIA driver already present (the CUDA template provides it), >= 12 GiB VRAM,
# >= 48 GiB RAM, >= 300 GB free on a fast disk.
set -Eeuo pipefail

PRESET="balanced"
ACCESS="local"
PORT="8080"
DO_CHECK=0
DO_STOP=0
DATA_DIR="${DATA_DIR:-$HOME/strata-data}"
MODEL_REPO="AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF"
MODEL_REV="4f1d2f730cff977961db81789e81bfc0d3e6dd2e"
ENGRAM_REPO="ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF"
ENGRAM_REV="cb02422c900df489cea5833e8a92171224059b3c"
UNSLOTH_REPO="unsloth/DeepSeek-V4.1-Flash-1017-GGUF"
UNSLOTH_REV="8a6ec9cf118e785a362ea94ee123c61c70553be6"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --preset) PRESET="$2"; shift 2 ;;
    --access) ACCESS="$2"; shift 2 ;;
    --port)   PORT="$2"; shift 2 ;;
    --data-dir) DATA_DIR="$2"; shift 2 ;;
    --check)  DO_CHECK=1; shift ;;
    --stop)   DO_STOP=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[36m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- hardware verdict
say "hardware"
command -v nvidia-smi >/dev/null 2>&1 || die "no NVIDIA driver. Use a CUDA image/template, or install the driver first."
VRAM_MIB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | sort -rn | head -1)
VRAM_GIB=$(awk -v m="$VRAM_MIB" 'BEGIN{printf "%.1f", m/1024}')
RAM_GIB=$(awk '/MemTotal/{printf "%.1f", $2/1048576}' /proc/meminfo)
FREE_GIB=$(df -BG --output=avail "$HOME" | tail -1 | tr -dc '0-9')
nvidia-smi --query-gpu=name,driver_version,compute_cap --format=csv,noheader | sed 's/^/    GPU: /'
echo "    VRAM: ${VRAM_GIB} GiB   RAM: ${RAM_GIB} GiB   free on \$HOME: ${FREE_GIB} GiB"
awk -v v="$VRAM_GIB" 'BEGIN{exit !(v>=11.5)}' || echo "    [!] under 12 GiB VRAM: it may start and crawl; 8 GiB is the documented floor"
awk -v r="$RAM_GIB" 'BEGIN{exit !(r>=46)}'   || echo "    [!] under 46 GiB RAM: untested territory, expect experts to be read from disk"
awk -v f="$FREE_GIB" 'BEGIN{exit !(f>=300)}' || echo "    [!] under 300 GiB free: the 2.00 bpw set needs ~257 GB"
[[ "$DO_CHECK" == 1 ]] && true
if [[ "$DO_CHECK" == 1 ]]; then say "check only - nothing installed"; exit 0; fi

if [[ "$DO_STOP" == 1 ]]; then strata launch --stop || true; exit 0; fi

command -v nvcc >/dev/null 2>&1 && NVCC=$(nvcc --version | grep -o 'release [0-9.]*' | awk '{print $2}') || NVCC="none"
echo "    nvcc: ${NVCC} (a headless box can rely on the driver + Strata's prebuilt engine)"

# ---------------------------------------------------------------- Strata, verified
say "install Strata (pinned + checksum-verified)"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
curl -fsSL https://github.com/Niko1221/Strata/releases/download/v0.2.13/install.ps1 -o "$TMP/win.ps1" || true
curl -fsSL https://github.com/Niko1221/Strata/releases/download/v0.2.13/SHA256SUMS.txt -o "$TMP/SHA256SUMS.txt"
curl -fsSL https://github.com/Niko1221/Strata/releases/download/v0.2.13/install.sh -o "$TMP/install.sh"
WANT=$(grep -E '  install\.sh$' "$TMP/SHA256SUMS.txt" | awk '{print $1}' | head -1)
GOT=$(sha256sum "$TMP/install.sh" | awk '{print $1}')
[[ -n "$WANT" && "$WANT" == "$GOT" ]] || die "install.sh checksum mismatch (want=${WANT:-none} got=$GOT)"
say "checksum ok: $GOT"
sh "$TMP/install.sh"
export PATH="$HOME/.local/bin:$HOME/.strata/bin:$PATH"
command -v strata >/dev/null 2>&1 || die "strata not on PATH after install; open a new shell and re-run"
strata --version

# ---------------------------------------------------------------- model files
say "model files (resumable; ~257 GB)"
python3 - <<'PY' || die "python3 is required on the rented box"
import sys
assert sys.version_info >= (3, 8), sys.version
PY
pip3 install --quiet --upgrade huggingface_hub hf_xet 2>/dev/null || pip install --quiet --upgrade huggingface_hub hf_xet

hf download "$MODEL_REPO" --revision "$MODEL_REV" --include "*IQ2_XXS*" --local-dir "$DATA_DIR"
hf download "$ENGRAM_REPO" --revision "$ENGRAM_REV" --include "*Engram-IQ4_NL*" --local-dir "$DATA_DIR"
hf download "$UNSLOTH_REPO" --revision "$UNSLOTH_REV" \
  --include "dspark-DeepSeek-V4.1-Flash-1017-Q8_0.gguf" \
  --include "mmproj-BF16.gguf" \
  --include "UD-Q8_K_XL/DeepSeek-V4.1-Flash-1017-UD-Q8_K_XL-00001-of-00009.gguf" \
  --local-dir "$DATA_DIR"

say "verify against the accepted pins"
python3 - "$DATA_DIR" <<'PY' || die "hash verification failed - do not launch on a bad shard"
import hashlib, os, sys
root = sys.argv[1]
# the same pins as manifests/acceptance.json in the repository
PINS = {
 "DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00001-of-00004.gguf": (39075714624, "d46efb67ccffd8fb5d7f18b423896381b9e06d8491e161c370ddf3b05b07e050"),
 "DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00002-of-00004.gguf": (39388449504, "cec1b2c3da429dc768b8bb9bc4dc4403d81f74d34db660a6a34ee3e555bf2c70"),
 "DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00003-of-00004.gguf": (39246891616, "9d9c2140fcb134a0b9a74dedd0e5167e68077af6d08ce7f856bce112f0a35dd3"),
 "DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00004-of-00004.gguf": (20527837312, "92e1b7aac2c27451977f093b89207a877221bba909424309450420f66fa42bf9"),
 "DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf": (110595290816, "eb19f30d368d393784e1fc54fdfaffc427ebb2110bf3762fdf5a8fbb9a2d740a"),
 "dspark-DeepSeek-V4.1-Flash-1017-Q8_0.gguf": (7976914240, "6ba6ac1b331c540691a209e7fc97dec2a24e295acb1e755c84c7d24a4373927a"),
 "mmproj-BF16.gguf": (972208288, "9a1ef7c40d0d702c7ed8c5f863f60abae64091387ba3fce0ad19ce9beeda3bf9"),
}
ALSO = {"DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf": {"3dac4c54893ad7aa89103c0028500eadc78e74112cef3a2930a97e67dc9fb4f3"}}
bad = 0
for name, (size, want) in PINS.items():
    path = os.path.join(root, name)
    if not os.path.exists(path):
        print(f"MISSING {name}"); bad += 1; continue
    got_size = os.path.getsize(path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 23), b""):
            h.update(chunk)
    digest = h.hexdigest()
    ok = got_size == size and (digest == want or digest in ALSO.get(name, set()))
    print(("PASS " if ok else "FAIL ") + name)
    bad += 0 if ok else 1
sys.exit(1 if bad else 0)
PY

# ---------------------------------------------------------------- launch
say "launch ($PRESET preset)"
case "$PRESET" in
  nuclear)   ARGS="--context 1m --speed full --parallel 8 --vision on --kv int8 --tune skip" ;;
  balanced)  ARGS="--context 128k --speed full --parallel 4 --vision off --kv int8 --tune quick" ;;
  code)      ARGS="--context 64k --speed full --parallel 2 --vision off --kv q4_0 --tune skip" ;;
  smoke)     ARGS="--context 8k --speed faster --parallel 1 --vision off --kv q4_0 --tune skip" ;;
  *) die "unknown preset $PRESET (nuclear|balanced|code|smoke)" ;;
esac
strata launch --family deepseek41 --model ist-das-2.00bpw --model-path "$DATA_DIR" \
  --data-dir "$DATA_DIR" --access "$ACCESS" --port "$PORT" $ARGS --no-tui --yes

KEY=$(strata launch --show-key 2>/dev/null || true)
cat <<EOF

────────────────────────────────────────────────────────────────────────
 ready. from your LAPTOP:

   ssh -N -L ${PORT}:127.0.0.1:${PORT} $(whoami)@<this-host>

 then point any OpenAI/Anthropic client at:
   http://127.0.0.1:${PORT}/v1          (OpenAI)
   http://127.0.0.1:${PORT}/v1/messages (Anthropic)
   API key: ${KEY:-<strata launch --show-key>}

 Claude Code / Codex / opencode:  strata connect <app>     (on the box)
 benchmark:                       python Tools/runtime/bench.py --url http://127.0.0.1:${PORT}/v1
 stop:                            strata launch --stop
────────────────────────────────────────────────────────────────────────
EOF
