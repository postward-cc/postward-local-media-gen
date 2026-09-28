# PENDING_WEIGHTS.md — review applicable license before downloading

H3 model weights require the user to review the current MiniMax H3 Community
License and confirm that the intended use and jurisdiction are covered before
any model download.

Sources:
- https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE
- https://platform.minimax.io/docs/guides/local-deploy-h3.md

## Local-ComfyUI weights needed for the T2V setup

| File | Size on disk | Source | Destination |
|---|---:|---|---|
| `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | 19.53 GB | `Comfy-Org/MiniMax-H3` revision `4cc1d817` | `ComfyUI/models/diffusion_models/` |
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | 14.61 GB | same | `ComfyUI/models/text_encoders/` |
| `minimax_h3_video_vae_fp16.safetensors` | 4.85 GB | same | `ComfyUI/models/vae/` |
| `minimax_h3_audio_vae_fp32.safetensors` | 0.56 GB | same | `ComfyUI/models/vae/` |
| `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` | 1.82 GB | `lightx2v/Minimax-h3-Turbo` | `ComfyUI/models/loras/` |
| **Total** | **~41.4 GB** | | |

Sizes verified with HTTP HEAD on 2026-09-20.

## Optional extras (only if R2V is needed)

- `minimax_h3_ref2va_pruned_int8_convrot.safetensors` (19.5 GB) — Ref2VA diffusion model

## Storage requirements

The pinned T2V weights require about 41.4 GB before output files and temporary
download data. Check available space on the filesystem containing
`comfyui-runtime/` before download:

```bash
df -h comfyui-runtime
```

## What to do after confirming license eligibility

From the repository root:

```bash
LICENSE_OK=1 ./comfyui-runtime/fetch_h3_weights.sh
./comfyui-runtime/launch.sh
```

Load `comfyui-runtime/workflows/video_minimax_h3_t2v.json` in ComfyUI.
