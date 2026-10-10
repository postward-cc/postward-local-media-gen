#!/usr/bin/env bash
# Clone VibeVoice assets and install its isolated TTS runtime under the XDG data home.
set -Eeuo pipefail

XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK="$ROOT/requirements-vibevoice.lock"
VIBEVOICE_HOME="${VIBEVOICE_HOME:-$XDG_DATA_HOME/postward/vibevoice}"
SOURCE_DIR="${VIBEVOICE_SOURCE:-$VIBEVOICE_HOME/source}"
VENV_DIR="${VIBEVOICE_HOME}/venv"
UV_BIN="${UV_BIN:-uv}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
SOURCE_REPO="https://github.com/vibevoice-community/VibeVoice.git"
SOURCE_REVISION="952326ddb264062466a888cf32a5b2f4e803e16e"
if ! command -v git >/dev/null; then
  echo "ERROR: git is required to clone the pinned VibeVoice voice presets." >&2
  exit 2
fi
if ! command -v "$UV_BIN" >/dev/null; then
  echo "ERROR: uv is required to create the pinned TTS runtime interpreter." >&2
  echo "  Install it with:  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  echo "  or set UV_BIN to an existing uv executable." >&2
  exit 2
fi

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

"$UV_BIN" python install "$PYTHON_VERSION"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  "$UV_BIN" venv --python "$PYTHON_VERSION" "$VENV_DIR"
fi
VENV_PYTHON="$VENV_DIR/bin/python"
"$ROOT/scripts/relock.sh" vibevoice
install_log="$VIBEVOICE_HOME/pip-install.log"
if "$UV_BIN" pip install --python "$VENV_PYTHON" --require-hashes -r "$LOCK" 2>&1 \
    | tee "$install_log"; then
  :
else
  echo >&2
  echo "The locked speech runtime did not install. Log: $install_log" >&2
  echo "Common causes:" >&2
  echo "  1. no network access to PyPI or the PyTorch wheel index" >&2
  echo "  2. free disk under $VIBEVOICE_HOME" >&2
  echo "  3. an artifact hash that no longer matches; re-run ./scripts/relock.sh vibevoice" >&2
  exit 4
fi

# Readiness is asserted, not printed: an environment without CUDA is installed
# but cannot generate speech, and saying "ready" there is a lie the next model
# would have to discover.
if "$VENV_PYTHON" - "$ROOT" <<'PY'
import sys
import torch
from transformers import AutoModelForTextToWaveform, AutoProcessor

sys.path.insert(0, sys.argv[1])
from voice_runtime.client import MIN_FREE_VRAM_MB as required

print(f"torch {torch.__version__}, cuda available: {torch.cuda.is_available()}")
if not torch.cuda.is_available():
    sys.exit("ERROR: the speech runtime has no usable CUDA device. "
             "Check nvidia-smi and the driver before preparing weights.")
free = None
if torch.cuda.is_available():
    free, _total = torch.cuda.mem_get_info()
    print(f"free VRAM: {free // (1024 * 1024)} MiB (need {required} MiB)")
    if free // (1024 * 1024) < required:
        sys.exit(f"ERROR: only {free // (1024 * 1024)} MiB free VRAM; "
                 f"{required} MiB is required for speech synthesis.")
print("VibeVoice runtime ready:", AutoModelForTextToWaveform.__name__)
PY
then
  :
else
  echo >&2
  echo "Weights can still be prepared, but synthesis will fail until this is fixed." >&2
  exit 5
fi
echo
echo "VibeVoice source and voice samples: $SOURCE_DIR"
echo "VibeVoice Python environment: $VENV_PYTHON"
echo "Model weights are NOT downloaded by bootstrap. After reviewing the model card, run:"
echo "  python voice_runtime/run.py prepare"
echo "Then check readiness:"
echo "  python voice_runtime/run.py status"
