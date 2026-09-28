# Forge local image runtime

This adapter uses an existing Forge installation configured with `FORGE_HOME`;
it does not install Forge packages, download weights, modify the installation,
stop processes, or call a hosted API. Inputs stay local and are POSTed to the
loopback Forge endpoint.

## 1. Readiness (no inference)

```bash
python scripts/doctor.py
python forge_runtime/run.py status
```

`status` reads `/sdapi/v1/options`, `/sdapi/v1/sd-models`, and
`/sdapi/v1/memory`. It does not load a model or start an inference. `doctor.py`
also reports whether the configured Forge launcher and SDXL checkpoint exist,
which checkpoint is loaded, and whether free VRAM exceeds the configured floor.

Defaults and overrides:

```text
FORGE_HOME                  required; existing local Forge installation
FORGE_CHECKPOINT_PATH       defaults to $FORGE_HOME/models/Stable-diffusion/sd_xl_base_1.0.safetensors
FORGE_URL                   http://127.0.0.1:7860
FORGE_MODEL                 sd_xl_base_1.0.safetensors
FORGE_PYTHON                $FORGE_HOME/venv/bin/python, or the repo runtime Python
FORGE_MIN_FREE_VRAM_MB      4096
```

Each value may be overridden via environment. Forge must have `--api` enabled.
The adapter refuses non-loopback URLs so a local source image cannot be sent to a
remote endpoint accidentally.

Start the existing Forge only if the user asks or approves a test that needs it:

```bash
./forge_runtime/launch.sh
```

This command stays in the foreground. Keep this terminal open and run generation
from a second terminal.

The launcher exits without duplicating Forge if the local API already responds;
otherwise it checks the expected checkpoint and starts the existing `webui.sh`
with loopback/API flags. `webui-user.sh` remains the authority for xformers and
VRAM/offload options. If this session started Forge interactively, stop only
that process from its own terminal (Ctrl-C) after its work; leave pre-existing
Forge/ComfyUI services and any other GPU process untouched.

## 2. The shared GPU lease is mandatory

Do **not** run `forge_runtime/run.py txt2img|img2img|inpaint` directly. The CLI
refuses inference without the queue's `POSTWARD_GPU_LOCK_HELD=1` marker. Use the
small typed wrapper:

```bash
python scripts/forge_job.py txt2img -- --prompt "..." --seed 431
python scripts/forge_job.py img2img -- --image ref.webp --prompt "..." --denoising-strength 0.35
python scripts/forge_job.py inpaint -- --image ref.webp --mask mask.png --prompt "..."
```

`forge_job.py` delegates to `scripts/job_queue.py run --kind forge-<operation>`;
the existing `flock` therefore serializes Forge with ComfyUI/H3 on
`comfyui-runtime/state/gpu.lock`. The queue places its stable job ID in
`POSTWARD_JOB_ID`, which names the output folder. This is the synchronous
serialized `run` path; `job_queue.py enqueue` only records queued metadata and
does not dispatch an inference worker.

## 3. Masked inpainting

```bash
python scripts/forge_job.py inpaint -- \
  --image /path/to/owl.webp \
  --mask /path/to/ears-mask.png \
  --prompt "Paint only the two ear tufts warm chestnut brown; preserve the same paper owl and everything outside the mask." \
  --negative-prompt "change owl shape, change eyes, change background, extra objects, text" \
  --denoising-strength 0.4 --mask-blur 3 --seed 431
```

Mask contract:

- The mask has the same pixel dimensions as the source image.
- White (`255`) means **editable**; black (`0`) means **protected**. Grey pixels
  feather the boundary. Use `--mask-edit black` only when the input convention is
  deliberately inverted.
- The mask goes to Forge's `img2img` endpoint as `mask`; the adapter sets
  `inpainting_mask_invert=0` for the white-editable convention.
- `--masked-content original` maps to Forge `inpainting_fill=1`, keeping the
  original latent as the inpaint initialization. Other explicit choices are
  `fill`, `latent-noise`, and `latent-nothing`.
- `--denoising-strength` is 0.45 by default and constrained to `[0, 1]`. Lower
  values preserve more of the source; higher values allow more redraw inside the
  mask. A low value does not guarantee exact preservation outside the mask if
  the model/Forge sampler has global colour correction enabled; verify the first
  smoke-test output pixel-by-pixel outside the mask.

Inputs must be readable PNG/JPEG/WebP. The 8 GB preset rejects images above
1280 px on either side or 1,310,720 pixels, and dimensions must be divisible by
8. It never silently downsizes or changes the mask geometry.

## 4. Output/provenance

Each successful job creates a unique `forge_runtime/outputs/<job_id>/` folder:
```text
01.png
manifest.json
```

The manifest records operation, local model, prompt/settings, output dimensions,
seed, source/mask SHA-256 and output SHA-256. It excludes inline image/mask bytes.
The output tree is git-ignored.

## 5. Failure behavior

- Forge unreachable or API disabled: fail before generation with endpoint detail.
- Wrong loaded checkpoint: fail; the adapter never silently switches models.
- Missing/free-VRAM endpoint or less than `FORGE_MIN_FREE_VRAM_MB`: fail before
  inference. Free the GPU or explicitly tune the threshold after measuring; the
  default is a guard, not an OOM guarantee.
- Image/mask size mismatch, unsupported dimensions, invalid denoising or mask
  mode: reject before network submission.
- Forge OOM/HTTP failure: preserve the queue failure status and response detail;
  do not automatically repeat the same expensive request.

## 6. Smoke-test status and gate

The user-authorized local smoke test passed on 2026-09-28: one SDXL inpaint,
1152×864, seed 431, 28 steps, denoising 0.4. Visual review found no visible
changes outside the ear tips. Pixel comparison measured 0.387% of unmasked
pixels with any difference (mean maximum-channel difference 0.0092; maximum
44), consistent with a small feathered-edge change. The output remains in the
user's local test folder; it is not checked into this repository.

This verifies that the local API, shared GPU queue, mask contract and output
manifest work end to end. It does **not** validate a multi-frame tutorial or
guarantee identical edits across frames. Before any new GPU run, confirm the
GPU is free and the user approves it; test one small mask and inspect its
outside-mask differences before batching. Forge and H3 inference must never run
concurrently on the 8 GB card.

### Observed local Forge warnings

On the configured workstation, Forge reports an xformers build mismatch and
falls back to PyTorch attention; the standard inpaint smoke test still passed.
Its built-in soft-inpainting extension also fails to load because `joblib` is
missing. Standard masked inpainting works; this adapter does not install
packages into Forge or depend on that extension.
