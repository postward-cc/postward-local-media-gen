#!/usr/bin/env bash
# Regenerate requirements-comfyui.lock from the pinned ComfyUI checkout.
#
# Run this after changing COMFYUI_VERSION, after changing
# requirements-core.txt or requirements-comfyui-extras.txt, and whenever a
# bootstrap reports that the lock is stale relative to the checkout.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMFYUI_REQS="$ROOT/comfyui-runtime/ComfyUI/requirements.txt"
LOCK="$ROOT/requirements-comfyui.lock"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu128}"
UV_BIN="${UV_BIN:-uv}"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: ./scripts/relock.sh [--dry-run]

Compiles the ComfyUI runtime into requirements-comfyui.lock with exact
versions and artifact hashes, then verifies that the torch family carries the
CUDA build tag the workstation profile expects.

Environment:
  UV_BIN                uv executable.
  PYTHON_VERSION        Interpreter version to resolve for; default is 3.12.
  TORCH_INDEX_URL       PyTorch CUDA wheel index.
EOF
}

while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if ! command -v "$UV_BIN" >/dev/null; then
  echo "ERROR: uv is required to compile the lock." >&2
  echo "  Install it with:  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 2
fi

if [[ ! -f "$COMFYUI_REQS" ]]; then
  echo "ERROR: $COMFYUI_REQS not found." >&2
  echo "  Run ./bootstrap.sh first, or set COMFYUI_VERSION and clone ComfyUI." >&2
  exit 2
fi

echo "Composing requirements from:"
echo "  requirements-core.txt"
echo "  requirements-comfyui-extras.txt"
echo "  comfyui-runtime/ComfyUI/requirements.txt"
echo

# PyTorch's index stays an extra index so ordinary packages resolve from PyPI.
# Reversing the two silently yields non-CUDA torch wheels, which relock.sh then
# rejects through scripts/doctor.py check-lock.
COMPILE=(
  "$UV_BIN" pip compile
  "$ROOT/requirements-core.txt"
  "$ROOT/requirements-comfyui-extras.txt"
  "$COMFYUI_REQS"
  --extra-index-url "$TORCH_INDEX_URL"
  --generate-hashes
  --python-version "$PYTHON_VERSION"
  --output-file "$LOCK"
)

if (( DRY_RUN )); then
  printf '+ '
  printf '%q ' "${COMPILE[@]}"
  printf '\n'
  exit 0
fi

"${COMPILE[@]}"

python3 "$ROOT/scripts/doctor.py" check-lock "$LOCK"
echo "Lock written: $LOCK"