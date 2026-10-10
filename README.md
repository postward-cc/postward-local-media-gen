# postward-local-media-gen

> Local image, speech and video generation toolkit for Postward users.

This repository packages the operational knowledge, workflows, scripts, and
OMP skill needed to run local media generation on consumer NVIDIA GPUs.
Current adapters:

- **Image**: local Stable Diffusion WebUI Forge / SDXL (`txt2img`, `img2img`,
  masked inpaint) plus lossless, mask-protected composition; uses an existing
  Forge install and sends no inputs to hosted image services
- **Video**: ComfyUI + MiniMax H3 open weights
- **Speech**: VibeVoice 1.5B-HF through Transformers; runtime and weights use
  the XDG data location or `VIBEVOICE_HOME`
- **Upscale**: NVIDIA RTX Video Super Resolution
- **Agent interface**: `SKILL.md` plus hardware-aware CLI modules

The repository is intentionally **skill-first** rather than MCP-first. A model
can inspect the decision tree, detect the local hardware, select a compatible
profile, queue a job, and recover from common failures. An MCP adapter can be
added later on top of the stable CLI seam.

## What the skill supports

- text-to-image (Forge/SDXL)
- image-to-image (Forge/SDXL)
- masked inpainting (Forge/SDXL; white mask pixels are editable)
- lossless CPU composition that preserves pixels outside a specified edit mask
- text-to-video (T2V), image-to-video (I2V), and reference-to-video (R2V template)
- multi-shot narrative sequences with explicit frame provenance
- text-to-speech and long-form speaker dialogue (VibeVoice 1.5B-HF)
- RTX VSR upscaling
- one GPU inference job at a time across Forge, ComfyUI/H3 and VibeVoice

## Start here

```bash
git clone https://github.com/postward-cc/postward-local-media-gen.git
cd postward-local-media-gen
cat SKILL.md
python scripts/doctor.py
```

Install the local adapter without modifying system Python or CUDA:

```bash
./bootstrap.sh
```

The bootstrap is idempotent and does **not** download H3 weights. See
`INSTALL.md` for options, `skill.json` for the machine-readable contract, and
`reference/license-compliance.md` before downloading licensed assets.

`doctor.py` returns JSON with GPU name, VRAM, free VRAM, CUDA/PyTorch state,
RAM, disk, weights detected, and the recommended profile. It also reports
`python_runtime` (both interpreters and whether the runtime venv survived),
`external_tools` (which local fallback tools exist, at which version) and
`vibevoice_environment` (whether the speech environment matches its lock).

## Local image generation (Forge)

Forge is an existing installation. Configure its location for this shell, then
check readiness without loading a model or starting inference:

```bash
export FORGE_HOME=/path/to/stable-diffusion-webui-forge
export FORGE_PYTHON="$FORGE_HOME/venv/bin/python"
python forge_runtime/run.py status
```

If Forge is stopped, run this in a dedicated terminal and leave it open:

```bash
./forge_runtime/launch.sh
```

In a second terminal:

```bash
python scripts/forge_job.py inpaint -- \
  --image /path/to/owl.webp --mask /path/to/ears.png \
  --prompt "Paint only the ear tufts chestnut brown." \
  --denoising-strength 0.4 --mask-blur 3 --seed 431
```

`status` is read-only. `launch.sh` starts the existing loopback Forge only if it
is not already responding and refuses startup below its VRAM floor. Run
generation through `forge_job.py`, not `forge_runtime/run.py`; it acquires the
same exclusive GPU lock as H3. Outputs and a provenance manifest go to
`forge_runtime/outputs/<job-id>/`. The full contract and failure recovery are in
[`forge_runtime/RUNBOOK.md`](forge_runtime/RUNBOOK.md). `scripts/doctor.py` is
the broader workstation/H3 diagnostic; Forge-only readiness is `run.py status`.

## Local speech generation (VibeVoice)

VibeVoice keeps its checkout, isolated Python environment and model cache under
the XDG data directory by default. Set `VIBEVOICE_HOME` to use another user-owned
data directory. Bootstrap installs dependencies and clones pinned source voice
samples; it does **not** download the 5.42 GB model:

```bash
./scripts/bootstrap_vibevoice.sh
python voice_runtime/run.py status
```

After reviewing the model terms, explicitly prepare weights:

```bash
VIBEVOICE_RESEARCH_OK=1 python voice_runtime/run.py prepare
python voice_runtime/run.py status
```


Generate only through the shared GPU queue:

```bash
VIBEVOICE_RESEARCH_OK=1 python scripts/vibevoice_job.py tts -- \
  --text "Olá! Este é um teste de fala em português." \
  --seed 431 --max-new-tokens 256
```

The selected 1.5B model card lists English and Chinese; Portuguese is
unsupported, so this command is an experimental quality check only. The model
card recommends research and development use, not commercial production.
The 8 GB profile requires at least 5632 MiB free VRAM. Its sampler cannot run
with the diffusion head offloaded to CPU.
Respect the audible disclosure/watermark and require recorded consent for any
real speaker reference. Details: [`voice_runtime/RUNBOOK.md`](voice_runtime/RUNBOOK.md)
and [`reference/license-compliance.md`](reference/license-compliance.md).


## Other local tools

The adapters above are the supported path. For work they do not cover, the
skill points to local headless tools — ImageMagick, libvips, G'MIC, OpenImageIO,
GIMP, Inkscape, qpdf, Ghostscript, ffmpeg, darktable-cli, rawtherapee-cli and
ExifTool — always in preference to a hosted service. CPU-only steps may run
alongside a queued inference job. A container may be used for such a step when
the user runs Docker; inference itself is never containerized. Details:
[`reference/docker-sidecars.md`](reference/docker-sidecars.md).

When several tools can do the same job, the skill prefers them in this order: a
repository adapter, then an external local tool that `doctor.py` reports
installed at a known version, then a container sidecar with a pinned digest. A
hosted service is never an option, and one step runs one engine.
`scripts/doctor.py` reports each known tool under `external_tools` with
`available`, resolved `path` and `version`, so availability is measured rather
than assumed.


## Repository layout

```text
postward-local-media-gen/
├── SKILL.md                              OMP entrypoint
├── skill.json                            machine-readable skill manifest
├── INSTALL.md                            installation contract
├── bootstrap.sh                          isolated idempotent bootstrap
├── requirements-core.txt                 this repo's own dependency (Pillow)
├── requirements-comfyui-extras.txt       ComfyUI CUDA extras
├── requirements-comfyui-v0.36.0.txt      pinned release's own requirements
├── requirements-comfyui.lock             ComfyUI runtime, exact versions + hashes
├── requirements-vibevoice.txt            speech runtime inputs
├── requirements-vibevoice.lock           speech runtime, exact versions + hashes
├── CONTEXT.md                            domain glossary
├── README.md                             this file
├── docs/adr/                             architectural decisions
│   └── 0001-skill-primary-interface.md
├── .github/workflows/ci.yml              runs scripts/check.sh, offline only
├── reference/                            model-facing operational references
│   ├── hardware-profiles.md
│   ├── concurrency.md
│   ├── image-generation.md
│   ├── license-compliance.md
│   ├── workflow-recipes.md
│   └── docker-sidecars.md                CPU-only container sidecars
├── voice_runtime/                        local VibeVoice TTS adapter
│   ├── RUNBOOK.md                        runtime, model, and usage guide
│   ├── client.py                         script parsing and HF model interface
│   └── run.py                            status, explicit model prepare, TTS
├── forge_runtime/                        local Forge / SDXL adapter
│   ├── RUNBOOK.md                        next-session operating guide
│   ├── launch.sh                         starts existing Forge; never installs
│   ├── client.py                         txt2img/img2img/masked inpaint
│   ├── masked_composition.py             pixel-protected edit composition
│   └── run.py                            status, CLI and provenance manifests
├── scripts/                              hardware and queue interfaces
│   ├── doctor.py
│   ├── forge_job.py                      Forge wrapper via shared GPU lock
│   ├── compose_masked_edit.py            CPU-only masked image compositor
│   ├── job_queue.py
│   ├── relock.sh                         regenerates the runtime locks
│   ├── check.sh                          offline gate; CI runs exactly this
│   ├── bootstrap_vibevoice.sh             optional TTS setup under XDG data
├── comfyui-runtime/                      ComfyUI implementation adapter
│   ├── RUNBOOK.md
│   ├── launch.sh
│   ├── fetch_h3_weights.sh
│   ├── run_workflow.py
│   ├── build_upscale_workflow.py
│   ├── submit_rtx_vsr.py
│   ├── run_hogwarts_shots.py
│   └── workflows/
├── tests/                                CPU-only contract tests, no GPU needed
│   ├── test_forge_runtime.py             payloads, VRAM guard, provenance
│   ├── test_masked_composition.py        protected-pixel behavior
│   ├── test_vibevoice.py                 storage, licence gate, language limits
│   ├── test_doctor.py                    capability probes, locks, drift
│   ├── test_job_queue.py                 GPU lease exclusivity, orphan recovery
│   └── test_bootstrap_guards.py          licence gate, version guards
```

## Hardware profiles

| VRAM | Default policy |
|---:|---|
| <8 GB | Do not use the official H3 8 GB profile; use a separately licensed INT4 profile or stop |
| 8–10 GB | INT8 + NVFP4, low-VRAM/offload, 0.2–0.4 MP, one job |
| 12–16 GB | INT8 + NVFP4, 0.4–0.6 MP, test high-VRAM mode |
| 16 GB+ | Native/high-VRAM profile, smoke test before 0.98 MP |


## Bootstrap the local adapter

```bash
./bootstrap.sh
```

The bootstrap creates an isolated environment under `comfyui-runtime/venv/`
using [`uv`](https://docs.astral.sh/uv/), installs ComfyUI and its custom
nodes, and does not download model weights. `uv` supplies and pins the
interpreter (CPython 3.12 by default, override with `PYTHON_VERSION`), so the
environment survives a system Python upgrade. Use:

```bash
python scripts/doctor.py
LICENSE_OK=1 ./comfyui-runtime/fetch_h3_weights.sh
./comfyui-runtime/launch.sh
```

See `INSTALL.md` for `--dry-run`, skip options, uninstall, and hardware-aware
installation details. The H3 weight download remains license-gated.

## Queueing and concurrent requests

Forge and H3 share one GPU lock. The supported `run` path is synchronous and
serializes inference:

```bash
python scripts/job_queue.py run --kind h3-t2v -- \
  python comfyui-runtime/run_workflow.py ...

python scripts/forge_job.py inpaint -- \
  --image /path/to/owl.webp --mask /path/to/ears.png \
  --prompt "Paint only the owl's ear tufts chestnut brown." --seed 431
```

`job_queue.py enqueue` records metadata only; there is no background dispatcher
in this repository. CPU-only ffmpeg work may run concurrently. Never run Forge
and H3 inference simultaneously on the same GPU.


## Verified video chain

On the RTX 4060 baseline:

```text
T2V 0.4 MP / 5 s       → 864×480, ~8 min
I2V continuity 0.6 MP  → 800×800, ~6 min
RTX VSR 2×             → 1600×1600, ~6 s
```

For narrative videos, use unique per-shot input names and a manifest containing
the source frame SHA-256. Never reuse a generic `last_frame.png` from a previous
run; stale source assets are indistinguishable from valid continuity unless
provenance is recorded.

Full commands and troubleshooting are in `comfyui-runtime/RUNBOOK.md`.

## License

The MiniMax H3 weights are governed by the
[MINIMAX H3 Community License](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE).
The reviewed revision lists the UK, EU, US, and South Korea as Excluded
Territories requiring separate licensing. Users are responsible for reviewing
the current terms and obtaining any required license.

The repository's scripts and skill references are intended for Postward
internal use. Upstream ComfyUI, model, and custom-node licenses remain
applicable to their respective artifacts.

## Provenance

- ComfyUI v0.36.0, commit `ee71d5c`
- Comfy-Org workflows revision `3c1df78`
- Comfy-Org H3 model revision `4cc1d817`
- Nvidia RTX nodes: `Comfy-Org/Nvidia_RTX_Nodes_ComfyUI`
