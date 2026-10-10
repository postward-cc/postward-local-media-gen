#!/usr/bin/env bash
# Everything CI runs, plus the local-only checks that need no GPU but do need
# the real adapter modules: workflow JSON validity, the saved-format to
# API-format conversion, and the settings a submission patches into a graph.
#
# CI deliberately does not run these. They are fast and offline, but they are
# here to give confidence before pushing an edit to the ComfyUI tools, and to
# keep that guarantee close to the machine that can act on a failure.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
UV_BIN="${UV_BIN:-uv}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
LOCAL_VENV="$ROOT/.local-check-venv"

echo "=== offline gate (same as CI)"
"$ROOT/scripts/check.sh"

echo
echo "=== local-only adapter checks"
if ! command -v "$UV_BIN" >/dev/null; then
  echo "ERROR: uv is required to build the pinned local check environment." >&2
  exit 2
fi

rm -rf "$LOCAL_VENV"
"$UV_BIN" python install "$PYTHON_VERSION" >/dev/null
"$UV_BIN" venv --python "$PYTHON_VERSION" "$LOCAL_VENV" >/dev/null
"$UV_BIN" pip install --python "$LOCAL_VENV/bin/python" -r requirements-core.txt >/dev/null

"$LOCAL_VENV/bin/python" -m unittest discover -s tests/local -t . "$@"
STATUS=$?
rm -rf "$LOCAL_VENV"
exit "$STATUS"