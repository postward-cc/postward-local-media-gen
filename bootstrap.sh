#!/usr/bin/env bash
# Bootstrap the local media-generation runtime without modifying system Python/CUDA.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="$ROOT/comfyui-runtime"
VENV="$RUNTIME/venv"
UV_BIN="${UV_BIN:-uv}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu128}"
COMFYUI_VERSION="${COMFYUI_VERSION:-v0.36.0}"
COMFYUI_REPO="${COMFYUI_REPO:-https://github.com/comfyanonymous/ComfyUI.git}"
RTX_NODES_REPO="${RTX_NODES_REPO:-https://github.com/Comfy-Org/Nvidia_RTX_Nodes_ComfyUI.git}"
DRY_RUN=0
SKIP_COMFYUI=0
SKIP_PYTHON_DEPS=0

usage() {
  cat <<'EOF'
Usage: ./bootstrap.sh [options]

Options:
  --dry-run             Check prerequisites and print actions only.
  --skip-comfyui       Do not clone/update ComfyUI or RTX custom nodes.
  --skip-python-deps   Do not create the venv or install Python packages.
  -h, --help           Show this help.

Environment:
  UV_BIN                uv executable that manages the interpreter and venv.
  PYTHON_VERSION        Interpreter version to pin; default is 3.12.
  TORCH_INDEX_URL       PyTorch wheel index; default is cu128.
  COMFYUI_VERSION       ComfyUI git tag; default is v0.36.0.
EOF
}

run() {
  if (( DRY_RUN )); then
    printf '+ '
    printf '%q ' "$@"
    printf '\n'
  else
    "$@"
  fi
}

# Sage Attention compiles against the installed PyTorch and CUDA toolkit, so it
# is the one package whose failure is environmental rather than a bad pin.
# A raw compiler trace says nothing useful about which of those is missing.
diagnose_install_failure() {
  local log="$1"
  {
    echo
    echo "The locked runtime did not install. Log: $log"
    echo
    if grep -qi 'sageattention' "$log"; then
      echo "Sage Attention builds from source against the installed PyTorch and"
      echo "CUDA toolkit, so this is an environment problem, not a bad pin. Check:"
      echo "  1. nvidia-smi works and reports the expected driver"
      echo "  2. nvcc is on PATH and matches the cu128 toolchain"
      echo "  3. free disk: Sage Attention needs a few GB to build"
      echo "  4. the runtime venv still has torch: ./comfyui-runtime/venv/bin/python -c 'import torch'"
      echo
      echo "  Sage Attention is an optional attention kernel. If none of the above"
      echo "  is fixable now, install without it and let ComfyUI fall back:"
      echo "    remove sageattention from requirements-comfyui-extras.txt, then"
      echo "    ./scripts/relock.sh comfyui && ./bootstrap.sh"
    else
      echo "Common causes:"
      echo "  1. no network access to PyPI or the PyTorch wheel index"
      echo "  2. free disk space under $RUNTIME"
      echo "  3. an artifact hash that no longer matches; re-run ./scripts/relock.sh"
    fi
  } >&2
}

while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --skip-comfyui) SKIP_COMFYUI=1 ;;
    --skip-python-deps) SKIP_PYTHON_DEPS=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if ! command -v git >/dev/null; then
  echo "ERROR: git is required." >&2; exit 1
fi
if ! command -v "$UV_BIN" >/dev/null; then
  cat >&2 <<EOF
ERROR: uv is required to create the pinned runtime interpreter.
  Install it with:  curl -LsSf https://astral.sh/uv/install.sh | sh
  or set UV_BIN to an existing uv executable.
EOF
  exit 1
fi
if ! command -v nvidia-smi >/dev/null; then
  echo "ERROR: nvidia-smi not found. Install a compatible NVIDIA driver first." >&2; exit 1
fi

run mkdir -p "$RUNTIME" "$RUNTIME/downloads" "$RUNTIME/hf-cache" \
  "$RUNTIME/logs" "$RUNTIME/outputs" "$RUNTIME/state" "$RUNTIME/workflows"

if (( ! SKIP_PYTHON_DEPS )); then
  # uv manages the interpreter itself, so the venv keeps working when the
  # workstation's system Python is upgraded or removed underneath it.
  echo "Pinned interpreter: CPython $PYTHON_VERSION (managed by $UV_BIN)"
  run "$UV_BIN" python install "$PYTHON_VERSION"
  if [[ ! -x "$VENV/bin/python" ]]; then
    echo "Creating isolated Python environment: $VENV"
    run "$UV_BIN" venv --python "$PYTHON_VERSION" "$VENV"
  fi
  VENV_PYTHON="$VENV/bin/python"
else
  VENV_PYTHON="$VENV/bin/python"
  if [[ ! -x "$VENV_PYTHON" && ! $DRY_RUN ]]; then
    echo "ERROR: --skip-python-deps requested but $VENV_PYTHON does not exist." >&2
    exit 1
  fi
fi

if (( ! SKIP_COMFYUI )); then
  if [[ ! -d "$RUNTIME/ComfyUI/.git" ]]; then
    run git clone --depth 1 --branch "$COMFYUI_VERSION" "$COMFYUI_REPO" "$RUNTIME/ComfyUI"
  fi

  RTX_DIR="$RUNTIME/ComfyUI/custom_nodes/Nvidia_RTX_Nodes_ComfyUI"
  if [[ ! -d "$RTX_DIR/.git" ]]; then
    run git clone --depth 1 "$RTX_NODES_REPO" "$RTX_DIR"
  fi
fi

if (( ! SKIP_PYTHON_DEPS )); then
  # Resolution reads the vendored requirements of the pinned ComfyUI release,
  # not the checkout, so the lock is reproducible from repository contents
  # alone. If COMFYUI_VERSION was overridden, the snapshot has to follow it.
  SNAPSHOT="requirements-comfyui-${COMFYUI_VERSION}.txt"
  if [[ ! -f "$ROOT/$SNAPSHOT" ]]; then
    cat >&2 <<EOF
ERROR: COMFYUI_VERSION is $COMFYUI_VERSION but $SNAPSHOT is not in this repository.
  Refresh the vendored requirements and the lock for that release:

    COMFYUI_VERSION=$COMFYUI_VERSION ./scripts/relock.sh --refresh-comfyui

  Resolution reads that snapshot, so skipping it would silently install the
  dependency set of a different ComfyUI release.
EOF
    exit 1
  fi

  echo "Compiling the ComfyUI runtime lock"
  run "$ROOT/scripts/relock.sh" comfyui
  run python3 "$ROOT/scripts/doctor.py" verify-locks
  if (( ! DRY_RUN )); then
    echo "Installing the locked runtime into $VENV"
    install_log="$RUNTIME/logs/pip-install.log"
    mkdir -p "$RUNTIME/logs"
    if "$UV_BIN" pip install --python "$VENV_PYTHON" --require-hashes \
        -r "$ROOT/requirements-comfyui.lock" 2>&1 | tee "$install_log"; then
      :
    else
      diagnose_install_failure "$install_log"
      exit 1
    fi
  fi
fi

if (( ! DRY_RUN )); then
  echo
  echo "Bootstrap complete. H3 weights were NOT downloaded."
  echo
  "$VENV_PYTHON" "$ROOT/scripts/doctor.py" || true
  echo
  echo "Next steps:"
  echo "  1. Review $ROOT/reference/license-compliance.md"
  echo "  2. If licensed: LICENSE_OK=1 $RUNTIME/fetch_h3_weights.sh"
  echo "  3. Start: $RUNTIME/launch.sh"
else
  echo "Dry run complete; no files or packages were changed."
fi
