# ADR 0003: uv-Managed Interpreter Instead of the System Python

- Status: accepted
- Date: 2026-10-10

## Context

A venv created with `python -m venv` symlinks `bin/python` to the
workstation's system interpreter. When that interpreter is upgraded or
removed, the venv stops existing and every adapter inside it dies with it.

This was not hypothetical. On the machine that prompted the change, the
runtime's `bin/python` pointed at a CPython that had been removed, leaving the
environment dead while its 20 GB of packages still sat on disk. Separately,
`bootstrap_vibevoice.sh` asserted the supported version range *against the
system Python*, so the machine could fail its own speech bootstrap.

`skill.json` declared a supported range while the only interpreter available
violated it, and nothing reported the mismatch.

## Decision

`bootstrap.sh` requires `uv`, pins CPython 3.12 via `uv python install`, and
creates the environment with `uv venv`. `PYTHON_BIN` is replaced by `UV_BIN`
and `PYTHON_VERSION`.

`scripts/doctor.py` reports `python_runtime`: the interpreter running the
doctor, whether it is in the supported range, and whether the runtime venv is
still usable.

## Consequences

Positive:

- The environment survives a system Python upgrade, because the interpreter
  lives under uv's own directory.
- The version is pinned rather than inherited from whatever the workstation
  happens to ship.
- Resolution and installation are much faster, which matters for a torch-sized
  dependency set.
- The doctor reports a broken environment instead of failing obscurely.

Negative:

- `uv` becomes a hard prerequisite. The bootstrap refuses without it and says
  how to install it.
- On a machine without uv, bootstrapping stops until it is installed. That is
  the intended trade: an explicit prerequisite beats an environment that dies
  silently later.

## Alternatives considered

**Keep `python -m venv` and re-run bootstrap when it breaks.** Rejected: the
failure is discovered when someone needs the tool, and the recovery destroys
and reinstalls every package.

**Pin by checking the system interpreter in doctor.** Rejected: it reports the
problem without preventing it.