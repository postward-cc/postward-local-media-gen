# Local image generation: Forge / SDXL

The image adapter is `forge_runtime/`, a client for an existing local Stable
Diffusion WebUI Forge installation selected through `FORGE_HOME`. It never
downloads weights, writes into the Forge installation, or sends images to a
remote service.

## Configure an existing local Forge install

Export the path discovered for the current workstation before checking or
starting Forge:

```bash
export FORGE_HOME=/path/to/stable-diffusion-webui-forge
export FORGE_CHECKPOINT_PATH="$FORGE_HOME/models/Stable-diffusion/sd_xl_base_1.0.safetensors"
export FORGE_PYTHON="$FORGE_HOME/venv/bin/python"
python forge_runtime/run.py status
```

`FORGE_HOME` and the SDXL checkpoint are user-provided machine configuration,
not repository defaults. `FORGE_URL` can select another local loopback port. If
Forge's Python environment differs, set `FORGE_PYTHON` to its interpreter or
install Pillow in the selected runtime. This repository never installs or
updates Forge.

## Operations

The CLI supports three operations:

- `txt2img`: text-to-image using `/sdapi/v1/txt2img`.
- `img2img`: reference-guided editing using `/sdapi/v1/img2img` and a low default denoising strength (`0.45`).
- `inpaint`: masked img2img. The API receives both `init_images` and `mask`; **white mask pixels are editable and black pixels are protected** by default. Gray mask pixels feather the boundary. `--mask-edit black` inverts this deliberately.

Example, one masked local edit:

```bash
python scripts/forge_job.py inpaint -- \
  --image /path/to/owl.webp \
  --mask /path/to/ears-mask.png \
  --prompt "Paint only the two owl ear tufts warm chestnut brown; preserve everything outside the mask exactly." \
  --negative-prompt "change owl shape, change eyes, change background, text" \
  --denoising-strength 0.4 \
  --mask-blur 3 \
  --seed 431
```

The image and mask must have identical dimensions. PNG, JPEG and WebP inputs are
read locally, converted to PNG data URIs in memory, and POSTed only to loopback
Forge. The adapter refuses non-loopback `FORGE_URL` values. It does not store
base64 image data in logs or manifests.

Example, text-to-image:

```bash
python scripts/forge_job.py txt2img -- \
  --prompt "A handmade paper owl on a light craft table" \
  --width 1024 --height 1024 --steps 28 --seed 431
```

Example, reference edit:

```bash
python scripts/forge_job.py img2img -- \
  --image /path/to/reference.webp \
  --prompt "Keep the same owl shape and palette; add small feather dots." \
  --denoising-strength 0.35 --seed 431
```

## Consistent multi-step photo sequences

Do not generate every tutorial panel independently with `txt2img`, even when
the prompt and seed match. A seed is not an identity lock; proportions,
placement, and parts can drift between calls.

1. Create and approve one full-scene reference at the final framing and aspect
   ratio. Keep the subject fully inside the frame with room for parts that will
   be added later.
2. Edit one tutorial change at a time, starting each stage from the previous
   stage. Keep the same canvas size and camera description. Review each raw
   model result before accepting it.
3. If a reference editor changes pixels outside the intended change, composite
   only the edited region back onto the approved previous stage:

   ```bash
   python scripts/compose_masked_edit.py \
     --base /path/to/previous-stage.png \
     --edit /path/to/model-edit.png \
     --mask /path/to/edit-region.png \
     --feather 4 \
     --out /path/to/next-stage.png
   ```

   The compositor requires identical dimensions, treats white mask pixels as
   editable and black as protected, writes lossless PNG, and verifies that
   protected pixels remain exactly equal. Gray pixels and `--feather` soften
   only the transition. It writes a sidecar manifest with SHA-256 for the base,
   edit, mask and output. Visually inspect seams; exact pixels outside a mask do
   not guarantee that the edited patch itself is plausible.

   Composition is CPU-only and does not acquire the GPU lock. The CLI refuses to
   overwrite inputs or existing outputs unless `--overwrite` is explicit.
4. Keep a transition review sheet and reject a frame if the object changes size,
   moves, loses a part, or gains an unrequested part. Read the tutorial's real
   step list before choosing what changes in each frame.

The first local comparison used Qwen Image Edit 2511 through ComfyUI 0.37.0
and `ComfyUI-GGUF` on an RTX 4060 8 GB (`torch 2.11.0+cu128`). It preserved
the robot better than independent prompts and edited one component at a time,
but raw outputs still changed unrelated pixels and sometimes over-expanded an
edit. The workflow then composited only the authorized patch onto the previous
stage. This profile is optional, not installed or downloaded by this
repository, and is **not** part of the Forge CLI.

Tested model files and provenance:

| File | Hugging Face source | ComfyUI folder | Bytes | SHA-256 |
|---|---|---|---:|---|
| `qwen-image-edit-2511-Q3_K_S.gguf` | [Unsloth Qwen Edit 2511 GGUF](https://huggingface.co/unsloth/Qwen-Image-Edit-2511-GGUF) | `models/unet/` | 9,218,914,912 | `d613d933c54ea2cace72bc556f803137c45363513677268283c08a5480a99309` |
| `qwen_2.5_vl_7b_fp8_scaled.safetensors` | [Comfy-Org Qwen Image ComfyUI](https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI) | `models/text_encoders/` | 9,384,670,680 | `cb5636d852a0ea6a9075ab1bef496c0db7aef13c02350571e388aea959c5c0b4` |
| `qwen_image_vae.safetensors` | [Comfy-Org Qwen Image ComfyUI](https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI) | `models/vae/` | 253,806,246 | `a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f` |

The GGUF loader is [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF)
(tested commit `6ea2651`). Together these files use about 18.9 GB of disk;
check disk and VRAM before downloading. The Qwen 2511 and Unsloth GGUF cards
list Apache-2.0; review the current terms and source revisions before use.
The 8 GB test used offloading and took about 6–9 minutes per edit. Do not
assume that result generalizes to other GPUs, ComfyUI versions, or quant files.

In the robot trial, the model produced seven sequential frames from the actual
tutorial order. Every transition changed pixels only within the component's
declared mask; the source frame, object scale, and camera remained fixed.
Buttons still looked somewhat glossy, and no hand/tool action was shown.
IP-Adapter Plus SDXL retained broad appearance but was less reliable at adding
the requested craft parts.

Direct `forge_runtime/run.py` generation calls refuse to run unless the shared
queue sets `POSTWARD_GPU_LOCK_HELD=1`. Use `scripts/forge_job.py` so Forge and
ComfyUI/H3 contend on the same `comfyui-runtime/state/gpu.lock`:

```text
request → job_queue.py run (exclusive flock) → Forge API → unique output folder
```

`job_queue.py enqueue` records a queued request; it does not itself dispatch a
worker. For immediate serialized execution use the documented `forge_job.py`
wrapper. Job kinds are `forge-txt2img`, `forge-img2img` and `forge-inpaint`.

## Readiness and VRAM guard

The Forge section in `python scripts/doctor.py` checks, without generating:

- whether the configured Forge launcher and SDXL checkpoint exist;
- whether the loopback API responds;
- the currently loaded checkpoint and available checkpoint list;
- Forge's CUDA free/total memory;
- whether the loaded checkpoint and free-memory threshold are suitable.

Each generation repeats the free-VRAM preflight immediately before submission.
The default minimum is 4096 MiB free (`FORGE_MIN_FREE_VRAM_MB` overrides it).
No generation is submitted if Forge cannot report free memory or the threshold
is not met. The threshold is an initial guard, not a guarantee against OOM; the
first real inpaint must be a one-image smoke test, at 1024 px or below, once the
user releases enough VRAM.

Forge inference and ComfyUI/H3 inference share the GPU lock. Do not generate an
image and video at the same time on an 8 GB card. The adapter never kills a
process to free VRAM; stop a known process only after the user's approval.

## Output and provenance

Each job writes one unique directory under `forge_runtime/outputs/<job_id>/`
(or `--out-dir`) containing `01.png` and `manifest.json`. The manifest records
operation, prompt/settings, loaded model, dimensions, seed, source/mask SHA-256,
output SHA-256, and `local_inference: true`; it never embeds image bytes.
Outputs are ignored by git because they are generated media.

## Model provenance

Do not download checkpoints or LoRAs as part of this adapter. The SDXL
checkpoint above is the user's existing install. Any model addition needs its
source, license, file size, hash, and target path recorded, plus a disk-space
check before download.
