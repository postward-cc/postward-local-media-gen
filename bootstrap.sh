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
  # The lock pins exact versions and artifact hashes for this repository's own
  # dependency, the ComfyUI runtime and the CUDA extras together. Regenerate it
  # with ./scripts/relock.sh whenever COMFYUI_VERSION or either requirements
  # file changes.
  echo "Compiling the ComfyUI runtime lock from the pinned checkout"
  run "$ROOT/scripts/relock.sh"
  run python3 "$ROOT/scripts/doctor.py" check-lock "$ROOT/requirements-comfyui.lock"
  if (( ! DRY_RUN )); then
    echo "Installing the locked runtime into $VENV"
    run "$UV_BIN" pip install --python "$VENV_PYTHON" --require-hashes \
      -r "$ROOT/requirements-comfyui.lock"
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
