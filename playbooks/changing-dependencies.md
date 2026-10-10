# Changing dependencies

Everything is resolved into a lock with exact versions and artifact hashes.
Editing a requirements file without regenerating the lock is a stale state, and
`scripts/doctor.py verify-locks` exists to fail exactly that — it is run by
`scripts/check.sh`, so CI catches it.

## Which file am I changing?

| File | Holds | Change it when |
|---|---|---|
| `requirements-core.txt` | This repository's own dependency (Pillow) | A first-party module needs a library |
| `requirements-comfyui-extras.txt` | Sage Attention, `nvidia-vfx`, `huggingface_hub` | The video runtime needs another CUDA extra |
| `requirements-comfyui-v<tag>.txt` | The pinned ComfyUI release's requirements | Never by hand — it is a snapshot |
| `requirements-vibevoice.txt` | The speech runtime inputs | The TTS runtime's pins change |

## The normal path

```bash
# 1. edit the input file
# 2. regenerate
./scripts/relock.sh
# 3. confirm both locks and the CUDA build tag
python scripts/doctor.py verify-locks
```

`relock.sh` takes `comfyui`, `vibevoice` or `all`. It verifies the lock before
writing, so a bad resolution fails at relock time rather than at first
inference.

## Bumping the ComfyUI release

```bash
COMFYUI_VERSION=v0.37.0 ./bootstrap.sh --skip-python-deps   # clone only
COMFYUI_VERSION=v0.37.0 ./scripts/relock.sh --refresh-comfyui
```

Then update **both** keys in `skill.json`:

```json
"comfyui_version": "v0.37.0",
"comfyui_requirements_snapshot": "requirements-comfyui-v0.37.0.txt"
```

and set `COMFYUI_VERSION` in `bootstrap.sh`. `verify-locks` compares the
declared snapshot name against the declared version, so a half-done bump fails
the gate rather than silently installing the previous release's dependency set.
Bootstrap refuses outright when the requested version has no snapshot.

Commit the new snapshot, the new lock, `skill.json` and `bootstrap.sh` together.

## The CUDA build tag

A PyTorch wheel without `+cu128` installs cleanly and fails much later, at
inference, with a missing-kernel error far from its cause. Resolution order
decides this silently: PyTorch as the primary index yields a PyPI build, PyPI
primary with PyTorch as an extra yields the CUDA build.

That is why `relock.sh` and `check-lock` enforce it:

```bash
python scripts/doctor.py check-lock requirements-comfyui.lock   # exit 1 if wrong
```

If a check fails, **fix the index ordering in `relock.sh`; do not relax the
check and do not pin around it.**

## Sage Attention

It compiles from source against the installed PyTorch and CUDA toolkit, so no
lock can fully guarantee it. When it fails, `bootstrap.sh` prints the log path
and an environment diagnosis. If it must be skipped, remove it from
`requirements-comfyui-extras.txt`, relock and re-run — ComfyUI falls back to a
slower attention path.

## Adding a package that needs an index

Not a core dependency. Put it in `requirements-comfyui-extras.txt` and give it a
`[[tool.uv.index]]`-style explicit index in the compile step. A package that
pulls CUDA wheels is exactly the case the CUDA tag check guards.

## Verify

```bash
./scripts/check.sh
```

The gate installs `requirements-core.txt` as part of the test step, so an input
file that stops resolving fails the check instead of the next workstation.