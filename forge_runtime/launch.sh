#!/usr/bin/env bash
# Start the user's existing Forge installation without modifying its config.
# No model download, package install, process kill, or VRAM-policy override here.
set -Eeuo pipefail

FORGE_HOME="${FORGE_HOME:-}"
FORGE_HOST="${FORGE_HOST:-127.0.0.1}"
FORGE_PORT="${FORGE_PORT:-7860}"
CHECKPOINT="${FORGE_CHECKPOINT_PATH:-}"
START_MIN_FREE_VRAM_MB="${FORGE_START_MIN_FREE_VRAM_MB:-5500}"

if [[ "$FORGE_HOST" != "127.0.0.1" && "$FORGE_HOST" != "localhost" && "$FORGE_HOST" != "::1" ]]; then
  echo "ERROR: local image generation must bind to loopback; refusing FORGE_HOST=$FORGE_HOST" >&2
  exit 2
fi
if [[ -z "$FORGE_HOME" ]]; then
  echo "ERROR: FORGE_HOME is not configured." >&2
  echo "Set FORGE_HOME to an existing Forge installation; this launcher never installs Forge." >&2
  exit 2
fi
if [[ -z "$CHECKPOINT" ]]; then
  CHECKPOINT="$FORGE_HOME/models/Stable-diffusion/sd_xl_base_1.0.safetensors"
fi
if [[ ! -x "$FORGE_HOME/webui.sh" ]]; then
  echo "ERROR: Forge launcher not found: $FORGE_HOME/webui.sh" >&2
  echo "Set FORGE_HOME to an existing Stable Diffusion WebUI Forge install." >&2
  exit 2
fi
if [[ ! -f "$CHECKPOINT" ]]; then
  echo "ERROR: SDXL checkpoint not found: $CHECKPOINT" >&2
  echo "This script never downloads model weights. Install and provenance-check the checkpoint first." >&2
  exit 2
fi
if command -v curl >/dev/null && curl --silent --fail --max-time 2 "http://$FORGE_HOST:$FORGE_PORT/sdapi/v1/options" >/dev/null; then
  echo "Forge API already responds at http://$FORGE_HOST:$FORGE_PORT; not starting a duplicate."
  exit 0
fi

# Forge loads SDXL on startup. Refuse before startup rather than evicting or
# stopping another known GPU process. The user can lower this guard explicitly.
if command -v nvidia-smi >/dev/null; then
  FREE_VRAM_MB="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1 | tr -d '[:space:]')"
  if [[ "$FREE_VRAM_MB" =~ ^[0-9]+$ ]] && (( FREE_VRAM_MB < START_MIN_FREE_VRAM_MB )); then
    echo "ERROR: only ${FREE_VRAM_MB} MiB VRAM is free; Forge startup guard is ${START_MIN_FREE_VRAM_MB} MiB." >&2
    echo "Free the GPU yourself or set FORGE_START_MIN_FREE_VRAM_MB after reviewing the risk. No process was stopped." >&2
    exit 3
  fi
fi

# The existing webui-user.sh owns xformers/medvram flags. Add only the API and
# loopback settings needed by this adapter. Do not edit the Forge installation.
exec "$FORGE_HOME/webui.sh" --api --server-name "$FORGE_HOST" --port "$FORGE_PORT"
