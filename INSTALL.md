# Install `postward-local-media-gen`

This repository is both an OMP skill and a local runtime bootstrap. A model
can clone the repo, read `SKILL.md`, run the doctor, and bootstrap the local
adapters without modifying system Python or the system CUDA toolkit.

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

- PyTorch, torchvision, torchaudio from the cu128 wheel index
- ComfyUI v0.36.0
- Sage Attention
- `nvidia-vfx`
- `huggingface_hub` CLI support
- `Comfy-Org/Nvidia_RTX_Nodes_ComfyUI`

It also creates the runtime directories and runs `scripts/doctor.py` using the
new venv. The system Python and `/usr/local/cuda` are not changed.

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
Transformers 5.17 runtime, but does not fetch model weights:

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
