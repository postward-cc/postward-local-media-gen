# ADR 0005: A Declared Tool Preference Order

- Status: accepted
- Date: 2026-10-10

## Context

Several tools can perform the same operation: masked inpainting exists as a
Forge operation and as a CPU-only compositor in this repository; a dozen local
headless tools can edit an image. An agent choosing among them had no written
rule, so the choice came down to whichever name was most familiar.

Separately, availability was assumed. Nothing reported whether a local tool was
installed, so an agent could state that a fallback existed on a machine where
it did not.

## Decision

`SKILL.md` declares a four-level order:

1. A repository adapter, because it owns the GPU lease, the manifest and the
   provenance contract.
2. An external local tool that `doctor.py` reports installed at a known version.
3. A container sidecar with a pinned digest.
4. Never a hosted service: user files stay on the workstation.

Ties resolve downward, and one step runs one engine — two composers over the
same output would leave the manifest unable to say what produced the file.

`scripts/doctor.py` reports `external_tools`, one entry per known tool with
`available`, resolved `path` and `version`, so availability is measured rather
than assumed. `scripts/check_contract.py` fails the build if a probed tool and
a declared tool disagree.

## Consequences

Positive:

- The choice becomes defensible instead of accidental, and an agent can say why
  it picked what it picked.
- Installing a tool becomes an explicit, informed step rather than a fallback
  discovered mid-task.
- Tool availability is evidence, consistent with the rest of the contract.

Negative:

- The probe list, the manifest and the documentation must be kept in agreement,
  which adds a maintenance obligation. That obligation is why
  `scripts/check_contract.py` exists.
- A tool installed only on one workstation will not be chosen on another, which
  is the intended behaviour but may surprise someone expecting uniformity.

## Alternatives considered

**Leave the choice to the agent.** Rejected: unrecorded choices are how a
second convention gets established.

**Probe nothing and rely on error messages.** Rejected: an error arrives after
the task is already blocked.