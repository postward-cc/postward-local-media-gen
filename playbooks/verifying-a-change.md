# Verifying a change

Two gates, one command each. CI runs the first; you run both.

## `./scripts/check.sh` — what CI runs

No GPU, no model weights, no running services. Roughly two seconds.

| Check | Catches |
|---|---|
| `bash -n` on every tracked shell script | Typos that only appear at runtime |
| `python -m json.tool skill.json` | A malformed contract an agent would read |
| `scripts/check_contract.py` | A tool probed but not declared, or vice versa; a playbook listed but missing; a document linking to a file that was renamed |
| `doctor.py verify-locks` | A requirements file edited without relocking; a torch build without `+cu128`; a ComfyUI snapshot that no longer matches the pinned version |
| Unit suite on the pinned interpreter | Contract regressions. Installing `requirements-core.txt` is part of this step, so the file must keep resolving |
| `doctor.py` JSON shape | An import break or a removed key that tooling depends on |

## `./scripts/check_local.sh` — adds the local-only checks

Runs everything above, then `tests/local/`: the committed workflow JSON, the
saved-format to API-format conversion, and the settings a submission patches
into a graph.

**CI deliberately does not run these.** They are offline and fast, but their
job is to give *you* confidence before pushing an edit to the ComfyUI tools:
that every workflow still converts to a submittable graph, that no link points
at a node that does not exist, and that the knobs a caller passes actually land
where they should.

Add to `tests/local/` rather than `tests/` when a check needs the real adapter
modules or is slow, but still must not run in CI.

## What no gate covers

| Area | How to verify | Cost |
|---|---|---|
| Actual image, video or speech generation | Run the adapter for real and read the manifest | GPU, minutes |
| VRAM behaviour under load | `python scripts/doctor.py`, then a real job at the profile boundary | GPU |
| GPU lock with a real second job | Launch two `scripts/job_queue.py run` processes | GPU |
| Forge behaviour | `python forge_runtime/run.py status`, then a one-image smoke test at ≤1024 px | GPU + Forge |
| Upgrade paths | `./bootstrap.sh --dry-run`, then a real bootstrap on a scratch machine | Disk, network |

None of these belong in CI, and pretending otherwise produces a green check
that proves nothing. Say in the commit what you ran and what you did not.

## Reviewing your own diff

Tests do not catch removal mistakes or documentation drift.

```bash
git diff --stat
grep -rn '<name-you-removed>' . | grep -v '^./ComfyUI'   # expect nothing
```

For a lock or dependency change, read the diff of the lock header and the
changed package list — that is where a wrong index order shows up.

## Commit message

State what changed and what it fixes. If something was verified by running it,
say so; if something remains unverified, say that too. An unstated gap is
worse than a stated one.