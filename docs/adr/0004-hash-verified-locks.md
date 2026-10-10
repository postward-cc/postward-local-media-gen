# ADR 0004: Hash-Verified Locks, Compiled from Vendored Inputs

- Status: accepted
- Date: 2026-10-10

## Context

The bootstrap installed torch, ComfyUI and the CUDA extras through separate
`uv pip install` calls with inline pins. Nothing recorded the resolved graph,
so a rerun could drift, and no artifact was checked against a known hash.

A second problem surfaced while fixing that one: index ordering during
resolution is silent. Compiling the real ComfyUI v0.36.0 dependency set with
the PyTorch index as the *primary* index resolved `torch==2.14.1` from PyPI —
a build with no CUDA. It installs without complaint and fails much later, at
inference, with a missing-kernel error far from its cause.

## Decision

Both runtimes are resolved by `uv pip compile` into
`requirements-comfyui.lock` and `requirements-vibevoice.lock`, with exact
versions and per-artifact hashes, and installed with `--require-hashes`.

Resolution reads **vendored** inputs from the repository:
`requirements-core.txt`, `requirements-comfyui-extras.txt`,
`requirements-vibevoice.txt`, and `requirements-comfyui-v<tag>.txt`, a snapshot
of the pinned release's own requirements. It never reads the live checkout, so
a lock is reproducible from repository contents alone.

`scripts/doctor.py verify-locks` enforces two invariants and runs in CI:

1. The torch family in a lock carries the `+cu128` CUDA build tag.
2. Every explicit `name==version` pin in an input file is honoured by its lock.

A local version tag satisfies a plain pin, because `torch==2.11.0` and
`torch==2.11.0+cu128` are the same release; a pin that itself carries a tag
must match exactly.

## Consequences

Positive:

- A reinstall produces the same versions, and the lock is reviewable in a diff.
- A wrong index resolution fails at bootstrap, naming the three packages.
- Editing a requirements file without relocking fails the gate.
- CI verifies the lock without cloning ComfyUI.

Negative:

- The lock must be regenerated on a ComfyUI version bump; a half-done bump
  fails the gate instead of silently installing the previous release's
  dependency set.
- Sage Attention builds from source against PyTorch and CUDA, so no lock fully
  guarantees it. The bootstrap keeps the log and explains the environment
  causes when it fails.
- `--require-hashes` accepts any artifact whose hash is listed, so it proves
  the download matched a reviewed artifact; it does not detect a single
  tampered line in a multi-platform hash block.

## Alternatives considered

**`uv sync` with a `pyproject.toml`.** Rejected: `uv` 0.12.23 has no
`dynamic-dependencies`, so ComfyUI's requirements would have to be copied by
hand into the project file.

**Recompiling in CI and diffing.** Rejected: resolution changes as upstream
publishes, so the check would fail for reasons unrelated to any change here.