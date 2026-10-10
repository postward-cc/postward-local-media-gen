#!/usr/bin/env bash
# Regenerate the runtime lock files from their pinned inputs.
#
# Run this after changing COMFYUI_VERSION, after changing any requirements
# file, and whenever a bootstrap reports that a lock is stale relative to the
# checkout it was compiled from.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMFYUI_DIR="$ROOT/comfyui-runtime/ComfyUI"
COMFYUI_SNAPSHOT="$ROOT/requirements-comfyui-v0.36.0.txt"
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
  comfyui      core + extras + the vendored ComfyUI requirements snapshot
  vibevoice    requirements-vibevoice.txt
  all          both (default)

Options:
  --refresh-comfyui   Copy requirements.txt from the pinned ComfyUI checkout
                      into the versioned snapshot, then relock. Run this after
                      changing COMFYUI_VERSION.

Environment:
  UV_BIN                uv executable.
  PYTHON_VERSION        Interpreter version to resolve for; default is 3.12.
  TORCH_INDEX_URL       PyTorch CUDA wheel index.
EOF
}

REFRESH_COMFYUI=0
while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --refresh-comfyui) REFRESH_COMFYUI=1 ;;
    --help) usage; exit 0 ;;
    comfyui|vibevoice|all) TARGET="$1" ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if ! command -v "$UV_BIN" >/dev/null; then
  echo "ERROR: uv is required to compile the locks." >&2
  echo "  Install it with:  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 2
fi

if (( REFRESH_COMFYUI )); then
  SOURCE_REQS="$COMFYUI_DIR/requirements.txt"
  if [[ ! -f "$SOURCE_REQS" ]]; then
    echo "ERROR: $SOURCE_REQS not found; clone the pinned ComfyUI checkout first." >&2
    echo "  COMFYUI_VERSION=$COMFYUI_VERSION ./bootstrap.sh --skip-python-deps" >&2
    exit 2
  fi
  echo "Refreshing $COMFYUI_SNAPSHOT from $SOURCE_REQS"
  if (( DRY_RUN )); then
    printf '+ cp %s %s\n' "$SOURCE_REQS" "$COMFYUI_SNAPSHOT"
  else
    cp "$SOURCE_REQS" "$COMFYUI_SNAPSHOT"
  fi
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
  if [[ ! -f "$COMFYUI_SNAPSHOT" ]]; then
    echo "ERROR: $COMFYUI_SNAPSHOT not found." >&2
    echo "  It is the vendored requirements of the pinned ComfyUI release." >&2
    echo "  Create it with: ./scripts/relock.sh --refresh-comfyui" >&2
    exit 2
  fi
  compile "$COMFYUI_LOCK" \
    "$ROOT/requirements-core.txt" \
    "$ROOT/requirements-comfyui-extras.txt" \
    "$COMFYUI_SNAPSHOT"
fi

if [[ "$TARGET" == "vibevoice" || "$TARGET" == "all" ]]; then
  compile "$VIBEVOICE_LOCK" "$VIBEVOICE_INPUT"
fi

if (( ! DRY_RUN )); then
  echo "Lock files are up to date."
fi