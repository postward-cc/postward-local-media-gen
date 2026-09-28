#!/usr/bin/env bash
# Clone VibeVoice assets and install its isolated TTS runtime under the XDG data home.
set -Eeuo pipefail

XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
VIBEVOICE_HOME="${VIBEVOICE_HOME:-$XDG_DATA_HOME/postward/vibevoice}"
SOURCE_DIR="${VIBEVOICE_SOURCE:-$VIBEVOICE_HOME/source}"
VENV_DIR="${VIBEVOICE_HOME}/venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu128}"
SOURCE_REPO="https://github.com/vibevoice-community/VibeVoice.git"
SOURCE_REVISION="952326ddb264062466a888cf32a5b2f4e803e16e"
if ! command -v git >/dev/null; then
  echo "ERROR: git is required to clone the pinned VibeVoice voice presets." >&2
  exit 2
fi
if ! command -v "$PYTHON_BIN" >/dev/null; then
  echo "ERROR: Python executable not found: $PYTHON_BIN" >&2
  exit 2
fi
"$PYTHON_BIN" -c 'import sys; assert (3, 11) <= sys.version_info[:2] < (3, 14), sys.version'

mkdir -p "$VIBEVOICE_HOME"
FREE_GB="$(df -BG --output=avail "$VIBEVOICE_HOME" | tr -dc '0-9')"
if [[ ! "$FREE_GB" =~ ^[0-9]+$ ]] || (( FREE_GB < 20 )); then
  echo "ERROR: at least 20 GiB free under $VIBEVOICE_HOME is required for the runtime and 5.42 GB model." >&2
  exit 3
fi

if [[ ! -e "$SOURCE_DIR" ]]; then
  git clone --filter=blob:none --no-checkout "$SOURCE_REPO" "$SOURCE_DIR"
  git -C "$SOURCE_DIR" sparse-checkout init --cone
  git -C "$SOURCE_DIR" sparse-checkout set demo/voices
  git -C "$SOURCE_DIR" checkout --detach "$SOURCE_REVISION"
else
  if [[ ! -d "$SOURCE_DIR/.git" ]]; then
    echo "ERROR: $SOURCE_DIR exists but is not the VibeVoice Git checkout; leaving it untouched." >&2
    exit 2
  fi
  CHECKED_OUT="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
  if [[ "$CHECKED_OUT" != "$SOURCE_REVISION" ]]; then
    echo "ERROR: existing VibeVoice checkout is $CHECKED_OUT, expected $SOURCE_REVISION; leaving it untouched." >&2
    exit 2
  fi
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
VENV_PYTHON="$VENV_DIR/bin/python"
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install --index-url "$TORCH_INDEX_URL" "torch==2.11.0"
"$VENV_PYTHON" -m pip install \
  "transformers==5.17.0" \
  "diffusers==0.35.2" \
  accelerate soundfile librosa

"$VENV_PYTHON" -c 'from transformers import AutoModelForTextToWaveform, AutoProcessor; import torch; print("VibeVoice runtime ready:", torch.__version__, torch.cuda.is_available(), AutoModelForTextToWaveform.__name__)'
echo
echo "VibeVoice source and voice samples: $SOURCE_DIR"
echo "VibeVoice Python environment: $VENV_PYTHON"
echo "Model weights are NOT downloaded by bootstrap. After reviewing the model card, run:"
echo "  python voice_runtime/run.py prepare"
echo "Then check readiness:"
echo "  python voice_runtime/run.py status"
