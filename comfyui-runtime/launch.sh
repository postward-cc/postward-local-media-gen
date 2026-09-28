#!/usr/bin/env bash
# Launch ComfyUI with H3-optimized flags for RTX 4060 8GB.
#
# Modes:
#   (default) LOW_VRAM   -- text encoders on CPU, diffusion offloaded, 1 GB VRAM headroom
#   novram              -- everything offloaded; slowest but safest for 8 GB
#
# Usage:
#   ./launch.sh                 # default LOW_VRAM mode
#   ./launch.sh novram          # most aggressive offload
#   ./launch.sh low 8189        # custom port
#   PORT=8189 LISTEN=0.0.0.0 ./launch.sh

set -euo pipefail

cd "$(dirname "$0")"

# ---- venv ----
# shellcheck disable=SC1091
source venv/bin/activate

# ---- config ----
PORT="${PORT:-8188}"
LISTEN="${LISTEN:-127.0.0.1}"
MODE="${1:-low}"  # low | novram
COMFYUI_RESERVE_VRAM="${COMFYUI_RESERVE_VRAM:-0.5}"

case "$MODE" in
  novram)
    VRAM_FLAGS=(--novram)
    ;;
  low|*)
    VRAM_FLAGS=(--lowvram --reserve-vram "$COMFYUI_RESERVE_VRAM")
    ;;
esac

# ---- env ----
export PYTHONUNBUFFERED=1
export HF_HUB_DISABLE_TELEMETRY=1
export TRANSFORMERS_NO_ADVISORY_WARNINGS=1
# Keep the HF cache in this runtime by default; callers may choose another location.
export HF_HOME="${HF_HOME:-$PWD/hf-cache}"
export COMFYUI_PATH="${COMFYUI_PATH:-$PWD/ComfyUI}"

echo "== ComfyUI launcher =="
echo "  venv      : $PWD/venv"
echo "  listen    : $LISTEN:$PORT"
echo "  mode      : $MODE (${VRAM_FLAGS[*]})"
echo "  hf cache  : $HF_HOME"
echo "  torch     : $(python -c 'import torch; print(torch.__version__, "cu"+torch.version.cuda.replace(".",""))')"
echo "  gpu       : $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr '\n' ' ')"
echo

mkdir -p "$HF_HOME" logs outputs

exec python ComfyUI/main.py \
  --listen "$LISTEN" \
  --port "$PORT" \
  --disable-pinned-memory \
  --use-sage-attention \
  --fp16-vae \
  "${VRAM_FLAGS[@]}"
