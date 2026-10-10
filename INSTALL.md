# Install `postward-local-media-gen`

This repository is both an OMP skill and a local runtime bootstrap. A model
can clone the repo, read `SKILL.md`, run the doctor, and bootstrap the local
adapters without modifying system Python or the system CUDA toolkit.

## Installing the skill into a harness

`SKILL.md` carries YAML frontmatter with `name`, `description` and
`metadata.version`, the format agent harnesses read to decide whether a skill
applies. That part is portable: it was verified against both OMP and Codex
skill packages, and it is the de facto convention rather than an OMP invention.

What is not portable is installation. Harnesses disagree about where skills
live and how they are registered. The portable path is the same for all of
them: **clone the repository, then point the harness at the directory.**

```bash
git clone https://github.com/postward-cc/postward-local-media-gen
cd postward-local-media-gen
```

Then, per harness. Every row was checked where the tool was available on this
machine; the rows marked "docs" come from the harness's documentation and
were not executed here.

| Harness | Install | Update |
|---|---|---|
| Any agent that reads Markdown | Clone and read `SKILL.md` | `./scripts/update.sh` |
| Codex | `codex plugin marketplace add postward-cc/postward-local-media-gen` then `codex plugin add postward-local-media-gen@postward` (**installed and verified**) | `codex plugin marketplace upgrade postward`; use Codex's plugin browser to refresh the installed plugin |
| OMP | `omp plugin link /path/to/postward-local-media-gen` (**dry run verified**) | `./scripts/update.sh` in the linked clone |
| opencode | `ln -s /path/to/postward-local-media-gen ~/.config/opencode/skills/postward-local-media-gen` (path convention verified from opencode docs and local layout; CLI not installed) | `./scripts/update.sh` in the symlinked clone |
| Claude Code | `/plugin marketplace add postward-cc/postward-local-media-gen`, then install `postward-local-media-gen@postward` (**docs**) | Third-party marketplace auto-update is **off by default**: enable it in `/plugin` → Marketplaces, or use `claude plugin update postward-local-media-gen@postward` (**docs**) |
| OMP registry | `omp skill install @<scope>/postward-local-media-gen` | `omp skill update`; not published |

`skill.json` carries the same table under `installation`, so an agent reading
the machine-readable contract finds the right command without parsing prose.

### Why Codex and opencode differ

**Codex and Claude Code read a catalog.** Both resolve a plugin from a
marketplace manifest committed to the repository, so the repository is
self-describing: add the repo, install by name. Codex accepts
`owner/repo`, an HTTPS git URL or an SSH URL, and `codex plugin marketplace
upgrade` refreshes the snapshot — the git equivalent of `git pull`.

**opencode reads a directory.** There is no marketplace and no git channel for
skills: it loads `~/.config/opencode/skills/<name>/SKILL.md`. Because this
repository has `SKILL.md` at its root, symlinking the clone into that directory
puts it exactly where opencode looks, and `git pull` inside the clone updates
it. That is the pattern already in use on this machine for other skills.

**OMP splits the two.** `omp skill install` only accepts a registry coordinate
and rejects a path or a git URL; `omp plugin link` accepts a directory. So the
git path for OMP goes through its plugin command.

### The manifests

Two families are committed, because two harnesses read two layouts:

| Path | Read by |
|---|---|
| `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | Claude Code; Codex also resolves these |
| `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json` | Codex natively, with its richer `interface` metadata |

Both declare the same marketplace name, `postward`, and both point at the
repository root (`.` for Claude Code, `./` for Codex) because the skill lives
there rather than in a subdirectory. `scripts/check_contract.py` holds each
manifest family to the name and version in `SKILL.md` and the same catalog name,
so neither can drift into advertising something else.

## Updating

There is no single update command shared by all harnesses. Each harness keeps
its own plugin/skill cache; the source stays a git repository. Use the path
that matches how you installed:

| Install method | Refresh |
|---|---|
| Plain clone, OMP `plugin link`, or OpenCode symlink | `./scripts/update.sh` in the clone |
| Codex Git marketplace | `codex plugin marketplace upgrade postward`, then `codex plugin add postward-local-media-gen@postward` |
| Claude Code marketplace | Enable auto-update in `/plugin` → Marketplaces (off by default for third-party markets), or `claude plugin update postward-local-media-gen@postward` |
| OMP skill registry | `omp skill update`; this skill is not published there |

The portable update script fast-forwards the tracked branch and then runs
`./scripts/check.sh`; if the gate fails it reports the commit that introduced
the breakage and how to return to the previous one. If the diff touches a
runtime input — `bootstrap.sh`, any `requirements-*`, `relock.sh` or
`bootstrap_vibevoice.sh` — it says to re-run the bootstrap, because the
environment and the repository have drifted apart.

For harness-managed installs, the harness refreshes its own cache from the
Git marketplace. It does not update the local clone. The manifests live in the
repo and their version/name agreement is checked by `scripts/check.sh`.

### Packaging constraints

The registry accepts up to 20 MiB unpacked, and **the packer includes untracked
and git-ignored files** — it does not read `.gitignore`. A workstation that has
run `./bootstrap.sh` holds a ComfyUI checkout and a venv, so publishing from it
fails on size until those are out of the way. Verified: a single 25 MB file
placed anywhere in the tree, including under a git-ignored path, is enough to
trip the limit.

This is why publishing belongs in CI, where `actions/checkout` gives a clean
tree by construction. Locally, publish from a checkout of the committed files:

```bash
git archive HEAD | tar -x -C /tmp/skill && cd /tmp/skill
omp skill publish --dry-run
```

CI runs `omp skill publish --dry-run` on every change in the `skill-package`
job, which validates the package against the registry's own rules without
publishing anything. Publishing for real needs a token
(`omp skill token`) stored as a repository secret, and a decision about
whether every merge to `main` should be released automatically — a merge that
passes the gate but breaks packaging would otherwise be released silently.

## Related: local media editing

This repository generates. Editing a finished asset — trimming a video,
burning subtitles, watermarking, resizing an image — is a sibling project,
[postward-creative-mcp](https://github.com/postward-cc/postward-creative-mcp),
which exposes ffmpeg and ImageMagick as agent tools over MCP. Docker is its only
dependency.

The two are independent: this skill invokes local scripts, while an MCP server
is mounted by the harness. Having one never requires the other. Read that
project's own README for registration steps, and see
[`reference/optional-tools.md`](reference/optional-tools.md) for why the local
server is the better choice for private material.

## Prerequisites

- NVIDIA driver (`nvidia-smi`) and git.
- [`uv`](https://docs.astral.sh/uv/), which supplies the interpreter and the
  venv:

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

  `uv` is used instead of `python -m venv` because a venv created that way
  symlinks to the workstation's system interpreter. When that interpreter is
  upgraded or removed, the venv stops existing and every adapter in it dies
  with it. A `uv`-managed interpreter lives in uv's own directory and survives
  that.

## Fast path

```bash
git clone https://github.com/postward-cc/postward-local-media-gen.git
cd postward-local-media-gen
./bootstrap.sh
```

`bootstrap.sh` does **not** download MiniMax H3 weights. Those files are about
41 GB and are protected by an explicit license gate.

## What bootstrap installs

Inside `comfyui-runtime/venv/` only:

- CPython 3.12, pinned and managed by `uv` (override with `PYTHON_VERSION`)
- everything in `requirements-comfyui.lock`: this repository's own dependency
  (Pillow), the pinned ComfyUI runtime and the CUDA extras, at exact versions
  with artifact hashes
- ComfyUI v0.36.0
- `Comfy-Org/Nvidia_RTX_Nodes_ComfyUI`

Everything else in `forge_runtime/`, `voice_runtime/` and `scripts/` runs on
the standard library alone, under whatever interpreter invokes the script.
`scripts/doctor.py` reports both interpreters under `python_runtime`, including
whether the venv is still usable.

It also creates the runtime directories and runs `scripts/doctor.py` using the
new venv. The system Python and `/usr/local/cuda` are not changed.

## The runtime locks

`requirements-comfyui.lock` is generated by `./scripts/relock.sh comfyui` from
three inputs: `requirements-core.txt` (this repository's own dependency),
`requirements-comfyui-extras.txt` (Sage Attention, `nvidia-vfx`,
`huggingface_hub`) and `requirements-comfyui-v0.36.0.txt`, which is a snapshot
of the pinned release's own requirements kept in this repository.

Resolution reads that snapshot, never the live checkout, so the committed lock
is reproducible from repository contents alone and stays verifiable without
cloning ComfyUI. On a version bump:

```bash
COMFYUI_VERSION=v0.37.0 ./bootstrap.sh --skip-python-deps
COMFYUI_VERSION=v0.37.0 ./scripts/relock.sh --refresh-comfyui
```

then update `comfyui_version` and `comfyui_requirements_snapshot` in
`skill.json`. Bootstrap refuses to install when the requested version has no
snapshot, rather than silently resolving the dependency set of another release.

`requirements-vibevoice.lock` is generated by `./scripts/relock.sh vibevoice`
from `requirements-vibevoice.txt`, and installs the speech runtime into its own
environment under the XDG data home. `./scripts/relock.sh` with no target does
both.

Both are installed with `--require-hashes`. Regenerate by hand after changing
`COMFYUI_VERSION` or any requirements file:

```bash
./scripts/relock.sh
```

The lock is also checked for the CUDA build tag. A PyTorch wheel without
`+cu128` installs without complaint and fails much later, at inference, with a
missing-kernel error far from its cause — so resolution order matters and the
result is verified rather than assumed:

```bash
python scripts/doctor.py check-lock requirements-comfyui.lock
```

A non-zero exit means the torch family resolved from PyPI instead of the
PyTorch index. Fix the index ordering in `scripts/relock.sh`, not the pin.

The doctor also measures an installed environment against its lock and reports
whether it is in sync, drifted, or absent. A drifted environment is not a
broken one, and the two are reported separately:

```bash
python scripts/doctor.py            # includes vibevoice_environment
```

## When an install fails

Both bootstraps keep the failing output in a log and explain the likely cause
instead of leaving a raw compiler trace on screen. Sage Attention gets a
specific diagnosis, because it builds from source against the installed
PyTorch and CUDA toolkit and its failures are environmental rather than a bad
pin:

```bash
less comfyui-runtime/logs/pip-install.log
```

## Checks before pushing

`./scripts/check.sh` runs everything that needs no GPU, no network and no
model weights: shell syntax, JSON validity, lock verification, the unit suite
on the pinned interpreter, and the shape of the doctor's JSON report. CI runs
exactly this script, so the local gate and the remote gate cannot drift.

```bash
./scripts/check.sh
```

Installing `requirements-core.txt` is part of the test step, which keeps that
file honest: if it stops resolving, the check fails rather than the next
workstation.

The suite covers the contracts a user depends on rather than internal wiring:
the GPU lease actually excludes a second inference job, orphaned jobs are
recovered, the H3 license gate refuses a download without the acknowledgement,
and an unknown ComfyUI version stops the bootstrap instead of silently
resolving another release's dependencies.

CI deliberately does not attempt generation. A hosted runner has no NVIDIA GPU,
and a test that never runs is worse than no test.

### Local-only checks

`./scripts/check_local.sh` runs everything above and then `tests/local/`: the
committed ComfyUI workflow JSON, its conversion to API format, and the settings
a submission patches into the graph. These never run in CI. Their job is to give
confidence before pushing an edit to the video and upscale tools — that every
workflow still produces a submittable graph, that no link points at a node that
does not exist, and that caller-supplied settings land where they should.

```bash
./scripts/check_local.sh
```

## Changing this repository

`playbooks/` holds task-oriented guides for agents: adding a local tool, adding
an adapter, removing or replacing something, changing a dependency, evaluating
a third-party CLI, and verifying a change. Start at
[`playbooks/README.md`](playbooks/README.md).

## Options

```bash
./bootstrap.sh --help
./bootstrap.sh --dry-run
./bootstrap.sh --skip-comfyui
./bootstrap.sh --skip-python-deps
TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128 ./bootstrap.sh
```

`--dry-run` prints actions and checks prerequisites without creating the venv,
cloning ComfyUI, or installing packages.

## Hardware behavior

The bootstrap detects `nvidia-smi`, but installation is intentionally conservative:
it installs the common cu128 PyTorch runtime and leaves generation profile
selection to `scripts/doctor.py` and `SKILL.md`.

```bash
python scripts/doctor.py
```

The doctor reports a profile:

- `4060-8gb`: INT8 + NVFP4, low-VRAM/offload, 0.2–0.4 MP
- `midrange`: 12–16 GB, 0.4–0.6 MP
- `native`: 16 GB+, smoke-test before 0.98 MP

## H3 license gate

After bootstrap, review the current MiniMax H3 license and confirm that your
use is permitted. Then, and only then:

```bash
LICENSE_OK=1 ./comfyui-runtime/fetch_h3_weights.sh
```

The script downloads the exact pinned components described in
`comfyui-runtime/PENDING_WEIGHTS.md`. It refuses to run without
`LICENSE_OK=1`.

## Start ComfyUI

```bash
./comfyui-runtime/launch.sh
```

Open `http://127.0.0.1:8188`.

## Run a job safely

One GPU inference job is allowed at a time:

```bash
python scripts/job_queue.py run --kind h3-t2v -- \
  python comfyui-runtime/run_workflow.py \
    comfyui-runtime/workflows/video_minimax_h3_t2v.json \
    --megapixels 0.4 --duration 5 --turbo-steps 8 \
    --prompt "A cinematic train station at dawn" \
    --out-dir comfyui-runtime/outputs/train-station
```

For concurrent logical requests, enqueue them rather than starting multiple
ComfyUI prompts:

```bash
python scripts/job_queue.py enqueue --kind h3-t2v \
  --payload '{"prompt":"a castle in the clouds"}'
python scripts/job_queue.py list
```

## Local image generation with Forge

Forge is a separate local installation; `bootstrap.sh` does not install it,
update it, or download SDXL weights. Set `FORGE_HOME` and, if needed,
`FORGE_CHECKPOINT_PATH` and `FORGE_PYTHON` for the current workstation:

```bash
export FORGE_HOME=/path/to/stable-diffusion-webui-forge
export FORGE_CHECKPOINT_PATH="$FORGE_HOME/models/Stable-diffusion/sd_xl_base_1.0.safetensors"
export FORGE_PYTHON="$FORGE_HOME/venv/bin/python"
```

Check Forge readiness without starting inference:

```bash
python forge_runtime/run.py status
```

`scripts/doctor.py` provides the broader hardware/H3 report. If Forge is
stopped, start it only after confirming free VRAM and user approval; the launcher
does not kill existing processes or modify `webui-user.sh`. It stays in the
foreground, so run it in a dedicated terminal:

```bash
./forge_runtime/launch.sh
```

Keep that terminal open. In a second terminal, run inference through
`scripts/forge_job.py`, which holds the same exclusive GPU lock as H3:

```bash
python scripts/forge_job.py txt2img -- \
  --prompt "A handmade paper owl on a craft table" --seed 431

python scripts/forge_job.py img2img -- \
  --image /path/to/reference.webp \
  --prompt "Keep the same owl; add a painted feather pattern." \
  --denoising-strength 0.35 --seed 431

python scripts/forge_job.py inpaint -- \
  --image /path/to/owl.webp --mask /path/to/ears-mask.png \
  --prompt "Paint only the two ear tufts chestnut brown." \
  --denoising-strength 0.4 --mask-blur 3 --seed 431
```

Inpaint masks use white for editable pixels and black for protected pixels.
Input/mask sizes must match; images are capped at 1280px per side and 1.25 MP
for the 8 GB profile. The default free-VRAM guard is 4096 MiB and can be
adjusted with `FORGE_MIN_FREE_VRAM_MB`. See `reference/image-generation.md` and
`forge_runtime/RUNBOOK.md` for the exact interface, output manifest, and OOM
recovery.

## Optional local speech generation with VibeVoice

VibeVoice uses an isolated Python environment, source checkout and model cache
under the XDG data directory by default; set `VIBEVOICE_HOME` to choose another
user-owned data directory. It does not alter the ComfyUI environment or system
Python. Bootstrap clones pinned source voice samples and installs the
Transformers 5.17 runtime into its own `uv`-managed CPython 3.12, but does not
fetch model weights:

```bash
./scripts/bootstrap_vibevoice.sh
```

Model preparation is a separate, explicit 5.42 GB download. Review the
research-only model card and supported-language limits in
`reference/license-compliance.md` before acknowledging it:

```bash
VIBEVOICE_RESEARCH_OK=1 python voice_runtime/run.py prepare
python voice_runtime/run.py status
```

Run inference through the shared GPU lease:

```bash
VIBEVOICE_RESEARCH_OK=1 python scripts/vibevoice_job.py tts -- \
  --text "Olá. Este é um teste experimental em português." \
  --seed 431 --max-new-tokens 256
```

The 8 GB profile requires at least 5632 MiB free VRAM. Keep other GPU inference
idle; the VibeVoice sampler cannot run with its diffusion head offloaded to CPU.

VibeVoice 1.5B lists English and Chinese; Portuguese output is unsupported and
must be reviewed as an experiment. Voice cloning requires explicit, recorded
consent. See `voice_runtime/RUNBOOK.md` for multi-speaker scripts, output
provenance, memory settings and recovery.


## Uninstall

`./bootstrap.sh` keeps ComfyUI files inside this checkout. The optional
VibeVoice runtime and cache use `VIBEVOICE_HOME`, defaulting to
`${XDG_DATA_HOME:-$HOME/.local/share}/postward/vibevoice`. There is no automatic
VibeVoice cleanup command; verify the configured directory is no longer needed
before removing it.

To remove only the ComfyUI runtime created by `./bootstrap.sh`, without touching
system Python or CUDA:

```bash
rm -rf comfyui-runtime/venv comfyui-runtime/ComfyUI
rm -rf comfyui-runtime/hf-cache comfyui-runtime/state
```

Do not delete model files unless you have confirmed they are no longer needed.
