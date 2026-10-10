# Playbooks

Task-oriented guides for changing this repository. Read the one that matches
what you are about to do, not the whole directory.

| Playbook | Use it when |
|---|---|
| [`adding-a-local-tool.md`](adding-a-local-tool.md) | A capability is missing and a local headless tool already covers it |
| [`adding-an-adapter.md`](adding-an-adapter.md) | The repository must own the operation: queue, manifest, GPU lock |
| [`removing-a-tool.md`](removing-a-tool.md) | Anything is being deleted or replaced |
| [`changing-dependencies.md`](changing-dependencies.md) | A version changes: ComfyUI, VibeVoice, Pillow, CUDA tag |
| [`evaluating-a-third-party-cli.md`](evaluating-a-third-party-cli.md) | An external tool might replace or complement an adapter |
| [`verifying-a-change.md`](verifying-a-change.md) | Before pushing: what runs locally, what runs in CI, what needs a GPU |

Two rules that apply to every playbook here:

- **Measure, do not assume.** A tool's presence is `doctor.py`, a version is a
  lock, a licence is a recorded source. Anything you claim must come from a
  command you ran.
- **Clean cutover.** When something is replaced, the old path is deleted:
  no shims, no re-exports, no deprecated aliases. A repository that supports
  two ways to do one thing has two ways to be wrong.

## The one-screen map

| Concern | Source of truth | Command |
|---|---|---|
| What the skill may do | `SKILL.md` | read it first |
| Machine-readable contract | `skill.json` | validate with `python -m json.tool` |
| Which local tools exist | `doctor.py` | `python scripts/doctor.py` |
| Which versions are installed | `requirements-*.lock` | `python scripts/doctor.py verify-locks` |
| Which tool to prefer | `SKILL.md` Tool preference order | — |
| Whether a change is sound | `scripts/check.sh` | CI runs exactly this |
| Whether the ComfyUI tools still parse | `tests/local/` | `./scripts/check_local.sh` |