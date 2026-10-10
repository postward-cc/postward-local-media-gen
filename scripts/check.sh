#!/usr/bin/env bash
# Run every check that needs no GPU, no network and no model weights.
#
# This is the single entry point used by CI and by contributors before pushing,
# so the gate cannot drift between the two. It deliberately does not attempt
# generation: a CI runner has no NVIDIA GPU, and a check that cannot run is a
# check that silently rots.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
UV_BIN="${UV_BIN:-uv}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
CHECK_VENV="$ROOT/.check-venv"
FAILED=0

step() { printf '\n=== %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1" >&2; FAILED=1; }

step "shell syntax"
while IFS= read -r script; do
  if bash -n "$script"; then
    printf 'ok   %s\n' "$script"
  else
    fail "$script"
  fi
done < <(git ls-files '*.sh')

step "json validity"
for json in skill.json; do
  if python3 -m json.tool "$json" >/dev/null; then
    printf 'ok   %s\n' "$json"
  else
    fail "$json"
  fi
done

step "committed locks"
if python3 scripts/doctor.py verify-locks >/tmp/verify-locks.json; then
  printf 'ok   locks match their inputs and carry the CUDA build tag\n'
else
  cat /tmp/verify-locks.json
  fail "lock verification"
fi

step "tests on the pinned interpreter"
if ! command -v "$UV_BIN" >/dev/null; then
  fail "uv not found; cannot build the pinned test environment"
else
  "$UV_BIN" python install "$PYTHON_VERSION" >/dev/null
  rm -rf "$CHECK_VENV"
  "$UV_BIN" venv --python "$PYTHON_VERSION" "$CHECK_VENV" >/dev/null
  # Installing from requirements-core.txt also proves that file still resolves:
  # it is the repository's only declared dependency.
  "$UV_BIN" pip install --python "$CHECK_VENV/bin/python" -r requirements-core.txt >/dev/null
  if "$CHECK_VENV/bin/python" -m unittest \
      tests.test_forge_runtime tests.test_masked_composition \
      tests.test_vibevoice tests.test_doctor 2>&1 | tail -3; then
    :
  else
    fail "unit tests"
  fi
  rm -rf "$CHECK_VENV"
fi

step "doctor reports a parseable summary"
if python3 scripts/doctor.py >/tmp/doctor.json 2>/dev/null; then
  :
else
  # No CUDA on a CI runner is expected and exits 2; the JSON must still parse.
  :
fi
if python3 -c '
import json, sys
report = json.load(open("/tmp/doctor.json"))
required = ["gpu", "torch", "python_runtime", "external_tools",
            "vibevoice_environment", "recommended_profile"]
missing = [key for key in required if key not in report]
if missing:
    print("missing doctor keys:", missing)
    sys.exit(1)
'; then
  printf 'ok   doctor JSON carries the documented keys\n'
else
  fail "doctor JSON shape"
fi

step "result"
if (( FAILED )); then
  echo "one or more checks failed" >&2
  exit 1
fi
echo "all offline checks passed"