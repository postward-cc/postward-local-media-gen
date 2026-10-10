# Adding an adapter

An operation this repository must own, because its output carries a job id,
SHA-256 provenance and GPU lock arbitration. The masked compositor
(`forge_runtime/masked_composition.py`) is the smallest complete example to
copy: 133 lines, one CLI, one manifest, no GPU.

## Before writing code

1. Read `SKILL.md` → **Operating contract**. An adapter must satisfy every
   numbered rule: unique output directory, recorded source hashes, the GPU lock
   for anything that uses the GPU.
2. Read `reference/concurrency.md`. If the adapter submits inference, it goes
   through `scripts/forge_job.py` or `scripts/job_queue.py run`; it never
   acquires the lock itself.
3. Read `reference/license-compliance.md` if it downloads weights or assets.
   Nothing implicit.

## The shape of an adapter

| Piece | Where | Rule |
|---|---|---|
| Client | `<runtime>/client.py` | Pure functions plus a thin transport. Keep imports at module level free of heavy libraries so `doctor.py` can import it |
| Operation | `<runtime>/run.py` | CLI, manifest writing, status |
| Queue wrapper | `scripts/<name>_job.py` | Holds the GPU lock; sets `POSTWARD_GPU_LOCK_HELD=1` |
| Manifest | `<runtime>/outputs/<job_id>/manifest.json` | SHA-256 of source, mask and output; `local_inference: true`; never embed image bytes |
| Status | `<runtime>/run.py status` | Read-only. Never loads a model to answer |
| Doctor block | `scripts/doctor.py` | Reports readiness without generating |
| Skill docs | `SKILL.md` Capabilities | The operation an agent should call |
| Machine contract | `skill.json` | adapter, command, queue command, gpu lock |

## Dependency rules

The repository declares exactly one third-party dependency today, and it is
spelled out in `requirements-core.txt`. If your adapter needs another:

```bash
echo 'nome==versão' >> requirements-core.txt
./scripts/check.sh          # installs it; the gate proves the file resolves
```

Adding a package does not just mean editing that file. Run the local check
afterwards; if it needs an index or a build step, you have added a ComfyUI
extra, not a core dependency — see
[`changing-dependencies.md`](changing-dependencies.md).

## Keep doctor.py importable

`doctor.py` imports adapter modules directly and must run on the standard
library alone. If your client module imports torch at module level, `doctor.py`
breaks. Probe heavy libraries from a subprocess instead, the way
`voice_runtime/run.py` builds its `-c "import torch, transformers..."` probe.

## Test the contract, not the wiring

Permanent tests must catch things a user would notice:

- a payload that omits a field the API requires;
- a manifest without the promised hashes;
- an output directory that collides;
- a refusal that does not actually refuse.

Do not test that a mocked HTTP call was forwarded, that a function called its
dependency, or that a constant equals itself.

```bash
./scripts/check.sh            # runs the suite
./scripts/check_local.sh      # plus the local-only adapter checks
```

## Verify

1. Run the operation once for real and read the manifest.
2. Confirm `doctor.py` status reports readiness without generating.
3. If it uses the GPU, confirm a second job blocks — `tests/test_job_queue.py`
   holds the pattern.