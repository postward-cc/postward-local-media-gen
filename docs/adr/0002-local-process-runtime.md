# ADR 0002: Local Processes, Not Containers, for Inference

- Status: accepted
- Date: 2026-10-10

## Context

The runtime was being hardened after the ComfyUI dependency chain was pinned.
The question surfaced directly: should Forge, ComfyUI/H3, RTX VSR and speech
run inside containers?

The project exists so a model can generate media on a workstation's own
NVIDIA GPU. `FORGE_HOME` points at an installation the user already has, with
their checkpoints and their Python environment, and the repository explicitly
refuses to install or update it.

## Decision

Adapters run as local processes. Containers are limited to CPU-only
post-processing that the adapters do not implement, per
`reference/docker-sidecars.md`.

## Consequences

Positive:

- The user's existing Forge install keeps working without being rebuilt inside
  an image, and the repository's promise not to install or update it survives.
- The GPU lease stays a plain `flock` on a shared path, which is the mechanism
  the concurrency contract is built on.
- The permission model stays explicit: bootstraps run only after the user asks
  for them.
- The system's CUDA toolkit and driver are untouched.

Negative:

- A workstation with a broken system Python or missing build tools needs the
  host repaired before anything runs.
- Isolation from the rest of the machine is weaker than a container's.
- Reproducibility depends on the pinned interpreter and locks rather than an
  image digest.

## Alternatives considered

**Containerise inference.** Rejected: it requires rebuilding the Forge
environment, matching the container's CUDA to the host driver, and sharing a
lock through a bind mount — turning the one mechanism the concurrency contract
depends on into the most fragile part. It also contradicts `FORGE_HOME`.

**A `uv` project with `uv sync`.** Rejected for the ComfyUI runtime: `uv`
0.12.23 has no `dynamic-dependencies`, so the upstream `requirements.txt`
would have to be hand-copied into `pyproject.toml`. Duplicating a third
party's dependency list is exactly the drift this repository now checks for.
See ADR 0004 for what was chosen instead.