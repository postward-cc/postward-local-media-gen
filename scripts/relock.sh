#!/usr/bin/env bash
# Regenerate the runtime lock files from their pinned inputs.
#
# Run this after changing COMFYUI_VERSION, after changing any requirements
# file, and whenever a bootstrap reports that a lock is stale relative to the
# checkout it was compiled from.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMFYUI_REQS="$ROOT/comfyui-runtime/ComfyUI/requirements.txt"
COMFYUI_LOCK="$ROOT/requirements-comfyui.lock"
VIBEVOICE_INPUT="$ROOT/requirements-vibevoice.txt"
VIBEVOICE_LOCK="$ROOT/requirements-vibevoice.lock"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu128}"
UV_BIN="${UV_BIN:-uv}"
TARGET="${1:-all}"
DRY_RUN=0
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && TARGET=""

usage() {
  cat <<'EOF'
Usage: ./scripts/relock.sh [comfyui|vibevoice|all] [--dry-run]

Compiles each runtime into a lock file with exact versions and artifact
hashes, then verifies that the torch family carries the CUDA build tag the
workstation profile expects.

Targets:
  comfyui      requirements-core.txt + extras + ComfyUI/requirements.txt
  vibevoice    requirements-vibevoice.txt
  all          both (default)

Environment:
  UV_BIN                uv executable.
  PYTHON_VERSION        Interpreter version to resolve for; default is 3.12.
  TORCH_INDEX_URL       PyTorch CUDA wheel index.
EOF
}

while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --help) usage; exit 0 ;;
    comfyui|vibevoice|all) TARGET="$1" ;;
    *) echo "Unknown target: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if ! command -v "$UV_BIN" >/dev/null; then
  echo "ERROR: uv is required to compile the locks." >&2
  echo "  Install it with:  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 2
fi

# PyTorch's index stays an extra index so ordinary packages resolve from PyPI.
# Reversing the two silently yields non-CUDA torch wheels, which the
# check-lock pass below rejects.
compile() {
  local output="$1"
  shift
  echo "Compiling $output from: $*"
  local args=(
    "$UV_BIN" pip compile "$@"
    --extra-index-url "$TORCH_INDEX_URL"
    --generate-hashes
    --python-version "$PYTHON_VERSION"
    --output-file "$output"
  )
  if (( DRY_RUN )); then
    printf '+ '
    printf '%q ' "${args[@]}"
    printf '\n'
    return 0
  fi
  "${args[@]}"
  python3 "$ROOT/scripts/doctor.py" check-lock "$output"
}

if [[ "$TARGET" == "comfyui" || "$TARGET" == "all" ]]; then
  if [[ ! -f "$COMFYUI_REQS" ]]; then
    echo "ERROR: $COMFYUI_REQS not found." >&2
    echo "  Run ./bootstrap.sh first, or clone the pinned ComfyUI checkout." >&2
    exit 2
  fi
  compile "$COMFYUI_LOCK" \
    "$ROOT/requirements-core.txt" \
    "$ROOT/requirements-comfyui-extras.txt" \
    "$COMFYUI_REQS"
fi

if [[ "$TARGET" == "vibevoice" || "$TARGET" == "all" ]]; then
  compile "$VIBEVOICE_LOCK" "$VIBEVOICE_INPUT"
fi

if (( ! DRY_RUN )); then
  echo "Lock files are up to date."
fi