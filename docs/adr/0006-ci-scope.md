# ADR 0006: CI Covers What a Hosted Runner Can Honestly Run

- Status: accepted
- Date: 2026-10-10

## Context

The repository had no CI, no pre-commit and no hooks. Locks, interpreter pins
and lock freshness depended on remembering to run commands by hand.

The obvious counter-argument is that the interesting things here are media
generation and GPU behaviour. A hosted runner has no NVIDIA GPU, no model
weights and no existing Forge installation, so none of it can run.

## Decision

`scripts/check.sh` is the gate and CI runs exactly that script: shell syntax,
JSON validity, lock verification, the unit suite on the pinned interpreter, and
the shape of the doctor's JSON. Running the same script locally is what keeps
the two from drifting apart.

Generation, VRAM behaviour, the GPU lease under real load and Forge smoke
tests are verified by hand on a workstation, and the commit says which were run
and which were not.

`scripts/check_local.sh` adds `tests/local/`: the committed workflow JSON, its
conversion to API format, and the settings a submission patches into a graph.
These are offline and fast, but they exist to give the person editing the
ComfyUI tools confidence before pushing. They never run in CI.

## Consequences

Positive:

- The gate and the remote gate cannot diverge.
- Nothing in CI pretends to test something it cannot run.
- Installing `requirements-core.txt` is part of the test step, so that file
  cannot stop resolving unnoticed.

Negative:

- Real generation stays untested by automation. This is a deliberate trade, not
  an oversight, and it is why the commits say what was run.
- The local-only checks are opt-in, so a contributor who only runs `check.sh`
  will not execute them.

## Alternatives considered

**Emulate a GPU in CI.** Rejected: an emulated run proves the harness works,
not that the code works on the hardware it targets.

**Skipping the GPU parts silently.** Rejected: the repository would then carry
CI-shaped assurance it does not have.