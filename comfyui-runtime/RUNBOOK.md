# ComfyUI + MiniMax H3 — RUNBOOK

The bootstrap creates an isolated ComfyUI runtime in this repository. Model
weights remain a separate, explicitly gated download. Check the actual GPU,
VRAM, RAM, and disk capacity before choosing a profile or running inference.

## Layout

```
comfyui-runtime/
├── venv/                          # Python 3.12 + torch 2.11.0+cu128
├── ComfyUI/                       # v0.36.0
│   ├── custom_nodes/
│   │   └── Nvidia_RTX_Nodes_ComfyUI/    # RTX Video Super Resolution
│   ├── input/                     # LoadImage / LoadVideo source dir
│   └── models/                    # H3 weights live here (41 GB)
│       ├── diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors
│       ├── loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors
│       ├── text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors
│       └── vae/
│           ├── minimax_h3_video_vae_fp16.safetensors
│           └── minimax_h3_audio_vae_fp32.safetensors
├── workflows/                     # official Comfy-Org pinned revision 3c1df78
│   ├── video_minimax_h3_t2v.json        # T2V template
│   ├── video_minimax_h3_i2v.json        # I2V template (first_frame path)
│   ├── video_minimax_h3_r2v.json        # R2V template (Ref2VA — needs Ref2VA weights)
│   ├── upscale-0.6mp.json               # generated: 0.4 → 0.6 MP H3 continue
│   └── rtx-vsr-upscale.json             # generated: any MP4 → RTX VSR
├── hf-cache/                      # huggingface_hub cache
├── logs/                          # per-launch stdout/stderr
├── outputs/                       # generated MP4s (gitignored)
├── downloads/                     # weight-download staging
├── launch.sh                      # ComfyUI launcher
├── run_workflow.py                # submit + monitor any saved-format workflow
├── build_upscale_workflow.py      # builds workflows/upscale-0.6mp.json from I2V template
├── submit_rtx_vsr.py              # direct-API RTX VSR submission (works around the
│                                  # DynamicCombo in saved-format JSON that confuses
│                                  # run_workflow.py)
├── fetch_h3_weights.sh            # gated weight downloader
├── monitor.py                     # VRAM/RAM/queue monitor
└── RUNBOOK.md                     # this file
```

## Pinned versions

| Component | Version |
|---|---|
| ComfyUI | v0.36.0 (commit ee71d5c, 2026-09-15) |
| Comfy-Org workflow templates | revision `3c1df78dedcc66c94ec27e0ed8a809ed7742f863` |
| Comfy-Org model repo | revision `4cc1d817b6184899b41293954329f576cb5ae86b` |
| PyTorch | 2.11.0+cu128 |
| Sage Attention | 1.0.6 (Linux) |
| nvidia-vfx | 0.1.0.1 (required by RTX VSR nodes) |
| Python | 3.12 |

## Launch ComfyUI

```bash
# Run from the repository root; keep the server terminal open.
./comfyui-runtime/launch.sh
./comfyui-runtime/launch.sh novram
PORT=8190 LISTEN=127.0.0.1 ./comfyui-runtime/launch.sh
```

`COMFYUI_RESERVE_VRAM` sets the low-VRAM reserve in GiB (default `0.5`). Adjust
it only after checking measured free VRAM and activation headroom.

### Flag rationale

| Flag | Reason |
|---|---|
| `--use-sage-attention` | Optimized attention path on supported NVIDIA configurations |
| `--disable-pinned-memory` | avoids pinned-memory regressions in some ComfyUI builds |
| `--fp16-vae` | matches the pinned Video VAE checkpoint dtype |
| `--lowvram --reserve-vram` | stages model weights through system RAM on constrained GPUs |
| `--novram` | most aggressive weight offload; slower, but may avoid OOM |

Choose flags for the measured GPU and installed model sizes. Do **not** use
`--cpu-vae` for H3 video VAE decoding unless testing confirms acceptable
performance.

GUI at `http://127.0.0.1:8188`. Drag `comfyui-runtime/workflows/*.json` into the window.

## Generation flow (T2V → optional I2V → optional RTX VSR)

```text
prompt ──► H3 text-to-video ──► optional first-frame continuation ──► optional RTX VSR
```

T2V, I2V and VSR all consume the shared GPU lease. Run one stage at a time and
verify each output before starting the next. Duration and memory depend on the
GPU, requested resolution and clip length.

### Step 1 — H3 0.2 MP smoke generation

```bash
python scripts/job_queue.py run --kind h3-t2v -- \
  python comfyui-runtime/run_workflow.py \
    comfyui-runtime/workflows/video_minimax_h3_t2v.json \
    --megapixels 0.2 --duration 1 --turbo-steps 8 --turbo-strength 1.0 \
    --seed 42 \
    --prompt "A small red balloon floats gently above a calm city street at golden hour." \
    --out-dir comfyui-runtime/outputs/t2v-smoke --timeout 1800
```

### Step 2 — Optional I2V continuation

Select the generated video path reported by the T2V job and extract a first
frame. Replace these shell variables with the paths returned for this job:

```bash
SOURCE_VIDEO="<T2V output path>"
FIRST_FRAME="comfyui-runtime/outputs/first-frame.png"
ffmpeg -y -sseof -0.1 -i "$SOURCE_VIDEO" \
  -frames:v 1 -update 1 "$FIRST_FRAME"

python comfyui-runtime/build_upscale_workflow.py \
  --frame "$FIRST_FRAME" --megapixels 0.4 --duration 2 \
  --turbo-steps 8 --seed 43 --prompt "Continue the same scene." \
  --out comfyui-runtime/workflows/user-i2v.json

python scripts/job_queue.py run --kind h3-i2v -- \
  python comfyui-runtime/run_workflow.py \
    comfyui-runtime/workflows/user-i2v.json \
    --megapixels 0.4 --duration 2 --turbo-steps 8 --seed 43 \
    --out-dir comfyui-runtime/outputs/i2v-continuation --timeout 1800
```

`build_upscale_workflow.py` copies the first frame into ComfyUI's input
directory and patches the I2V template. Dimensions must match the selected
aspect ratio and model constraints. I2V memory behavior is hardware-dependent;
begin with low resolution, use `novram` when the profile requires it, and stop
on repeated OOM or model-placement errors. Do not apply untracked local patches
to the ComfyUI checkout.

### Step 3 — Optional RTX Video Super Resolution

Pass an output path reported by the preceding job:

```bash
python scripts/job_queue.py run --kind rtx-vsr -- \
  python comfyui-runtime/submit_rtx_vsr.py \
    --input "<I2V output path>" \
    --output-dir comfyui-runtime/outputs/upscaled \
    --multiplier 2 --quality ULTRA --timeout 600
```

`submit_rtx_vsr.py` builds the RTX VSR prompt API directly because the node's
`DynamicCombo.Input` does not round-trip cleanly through saved-format widgets.

## I2V from a reference image

The I2V template accepts a reference frame as the first frame. Keep the source
asset and all generated results in user-owned storage; do not add them to this
repository.

```bash
INPUT_FRAME="<user-provided image path>"
WORKFLOW="comfyui-runtime/outputs/i2v-workflow.json"

python comfyui-runtime/build_upscale_workflow.py \
  --frame "$INPUT_FRAME" \
  --aspect-ratio "16:9 (Widescreen)" \
  --megapixels 0.2 --duration 1 --turbo-steps 8 --seed 44 \
  --prompt "Describe the desired motion." \
  --out "$WORKFLOW"

# Start only after checking the free GPU and confirming no other inference runs.
./comfyui-runtime/launch.sh novram

python scripts/job_queue.py run --kind h3-i2v -- \
  python comfyui-runtime/run_workflow.py "$WORKFLOW" \
    --megapixels 0.2 --duration 1 --turbo-steps 8 --seed 44 \
    --out-dir comfyui-runtime/outputs/i2v --timeout 1800
```

The builder copies the first frame to ComfyUI's input directory and patches
the I2V workflow. Rescale it to the selected aspect ratio; dimensions must be
compatible with the workflow. I2V memory use varies with GPU, frame size and
clip duration. Smoke-test one short clip before scaling up. ComfyUI upstream
updates can change offload behavior; report repeatable failures rather than
applying untracked source patches.
## Recipe variants

| Recipe | Megapixels | Output (multiple=32) | Duration | Turbo steps |
|---|---|---|---|---|
| 0.2 MP smoke | 0.2 | 608×352 | 1 s | 8 |
| 0.4 MP standard | 0.4 | 864×480 | 5 s | 8 |
| 0.6 MP upscale | 0.6 | 1056×608 (or square on some templates) | 2 s | 8 |
| 0.98 MP native | 0.98 | 1344×768 | 5 s | 20 (no Turbo) |

Avoid `megapixels=1.0` exactly — it resolves to 1376×768 which is above H3-Base's 768×1344 pixel-area cap.

## Troubleshooting

| CUDA OOM during sampling | requested resolution/duration exceeds free VRAM | lower megapixels/duration; choose the measured offload mode; never overlap inference |
| VAE dtype mismatch | VAE precision does not match the checkpoint | keep the launcher's `--fp16-vae` setting |
| Attention op requires CUDA | selected attention backend cannot run on CPU | keep VAE on GPU or use the supported PyTorch attention fallback |
| Missing RTX VSR `scale` input | saved-format widget does not encode the V3 DynamicCombo | use `submit_rtx_vsr.py` |
| T2V output has no audio | audio VAE is missing | install the license-gated H3 weights and confirm both VAE files exist |
| I2V OOM or VAE decode/device-placement failure | frame encode/decode has a higher peak than T2V | reduce frame size/duration, try the supported offload mode, and stop if it still fails; this repo does not patch ComfyUI internals |
| VSR output is absent from the output folder | ComfyUI returned a V3 image/video output not found by the wrapper | inspect the job response and use the documented RTX VSR fetch path |

## Hardware limits and updates

H3 uses dynamic weight loading and system-RAM offload. Actual VRAM/RAM peaks and
generation speed vary by GPU, ComfyUI version, model files and requested clip.
Read `python scripts/doctor.py`, leave headroom, and use small smoke tests.
Do not apply local source patches to the ComfyUI checkout as part of setup.

The repository pins ComfyUI, workflow templates and H3 model revisions.
Upgrade those pins only as a reviewed repository change, then run one T2V smoke
test and separately exercise I2V/VSR before recommending the new version.
H3 model-weight downloads remain license-gated.

The H3 weights themselves are pinned to Comfy-Org revision `4cc1d817` (and the Turbo LoRA to `lightx2v/Minimax-h3-Turbo`); re-running `LICENSE_OK=1 ./fetch_h3_weights.sh` after a model repo update will refresh them.
