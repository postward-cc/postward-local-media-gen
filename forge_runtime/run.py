#!/usr/bin/env python3
"""Forge local-generation CLI: status, txt2img, img2img and masked inpaint.

Generation is local-only and guarded by the measured Forge CUDA free-memory
endpoint. For production use, invoke through `scripts/forge_job.py`, which holds
the same exclusive GPU file lock as ComfyUI/H3.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forge_runtime.client import (
    DEFAULT_CFG, DEFAULT_MIN_FREE_VRAM_MB, DEFAULT_SAMPLER, DEFAULT_SCHEDULER,
    ForgeClient, ForgeError, ImageInput, build_img2img_payload,
    build_inpaint_payload, build_txt2img_payload, load_image,
)

DEFAULT_OUTPUT = ROOT / "forge_runtime" / "outputs"
DEFAULT_MODEL = "sd_xl_base_1.0.safetensors"


def job_id() -> str:
    return os.environ.get("POSTWARD_JOB_ID") or f"forge-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def safe_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove inline base64 image data before writing the manifest."""
    return {key: value for key, value in payload.items() if key not in {"init_images", "mask"}}


def save_result(
    images: list[bytes], *, operation: str, payload: dict[str, Any],
    status: dict[str, Any], out_root: str | Path | None = None,
    source: ImageInput | None = None, mask: ImageInput | None = None,
    requested_model: str | None = None, provider_info: str | None = None,
    provider_parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist outputs and a local provenance manifest in a unique job folder."""
    destination = Path(out_root).expanduser() if out_root else DEFAULT_OUTPUT
    folder = destination / job_id()
    folder.mkdir(parents=True, exist_ok=False)
    outputs = []
    for index, data in enumerate(images, start=1):
        name = f"{index:02d}.png"
        path = folder / name
        path.write_bytes(data)
        outputs.append({"path": str(path.resolve()), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})

    manifest = {
        "job_id": folder.name,
        "status": "success",
        "operation": operation,
        "local_inference": True,
        "forge_url": status.get("base_url"),
        "model": status.get("model"),
        "model_filename": status.get("model_filename"),
        "model_sha256": status.get("model_sha256"),
        "requested_model": requested_model,
        "cuda_free_mb_at_submit": status.get("cuda_free_mb"),
        "cuda_total_mb": status.get("cuda_total_mb"),
        "resolution": f"{payload.get('width')}x{payload.get('height')}",
        "seed": payload.get("seed"),
        "settings": safe_settings(payload),
        "provider_parameters": safe_settings(provider_parameters or {}),
        "provider_info": provider_info,
        "source": ({"path": str(source.path), "sha256": source.sha256} if source else None),
        "mask": ({"path": str(mask.path), "sha256": mask.sha256} if mask else None),
        "mask_semantics": "white pixels are editable; black pixels are protected" if mask else None,
        "outputs": outputs,
        "warnings": [],
    }
    temp = folder / "manifest.json.tmp"
    temp.write_text(json.dumps(manifest, indent=2) + "\n")
    temp.replace(folder / "manifest.json")
    return manifest


def _base_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--negative-prompt", default="")
    parser.add_argument("--steps", type=int, default=28)
    parser.add_argument("--cfg-scale", type=float, default=7.0)
    parser.add_argument("--sampler", default=DEFAULT_SAMPLER)
    parser.add_argument("--scheduler", default=DEFAULT_SCHEDULER)
    parser.add_argument("--seed", type=int, default=-1)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--min-free-vram-mb", type=int, default=int(os.environ.get("FORGE_MIN_FREE_VRAM_MB", str(DEFAULT_MIN_FREE_VRAM_MB))))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("FORGE_URL"))
    sub = parser.add_subparsers(dest="operation", required=True)

    sub.add_parser("status", help="read Forge readiness, checkpoint list and CUDA free VRAM")

    txt = sub.add_parser("txt2img", help="generate one image from text")
    _base_args(txt)
    txt.add_argument("--width", type=int, default=1024)
    txt.add_argument("--height", type=int, default=1024)

    img = sub.add_parser("img2img", help="edit an image using a reference image")
    _base_args(img)
    img.add_argument("--image", type=Path, required=True)
    img.add_argument("--denoising-strength", type=float, default=0.45)

    paint = sub.add_parser("inpaint", help="edit only the white region of a mask")
    _base_args(paint)
    paint.add_argument("--image", type=Path, required=True)
    paint.add_argument("--mask", type=Path, required=True)
    paint.add_argument("--denoising-strength", type=float, default=0.45)
    paint.add_argument("--mask-blur", type=int, default=4)
    paint.add_argument("--mask-edit", choices=("white", "black"), default="white")
    paint.add_argument("--inpaint-full-res", action="store_true")
    paint.add_argument("--inpaint-full-res-padding", type=int, default=32)
    paint.add_argument("--masked-content", choices=("fill", "original", "latent-noise", "latent-nothing"), default="original")
    return parser


def _fill_index(value: str) -> int:
    return {"fill": 0, "original": 1, "latent-noise": 2, "latent-nothing": 3}[value]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        client = ForgeClient(args.url)
        if args.operation != "status" and os.environ.get("POSTWARD_GPU_LOCK_HELD") != "1":
            raise ForgeError(
                "GPU inference must run under the shared GPU lease. "
                "Use `python scripts/forge_job.py ...` instead of calling run.py directly."
            )
        if args.operation == "status":
            print(json.dumps(client.status(), indent=2))
            return 0

        if args.operation == "txt2img":
            payload = build_txt2img_payload(
                prompt=args.prompt, negative_prompt=args.negative_prompt,
                width=args.width, height=args.height, steps=args.steps,
                cfg_scale=args.cfg_scale, sampler=args.sampler,
                scheduler=args.scheduler, seed=args.seed,
            )
            source = mask = None
        elif args.operation == "img2img":
            source = load_image(args.image)
            mask = None
            payload = build_img2img_payload(
                image=source, prompt=args.prompt, negative_prompt=args.negative_prompt,
                denoising_strength=args.denoising_strength, steps=args.steps,
                cfg_scale=args.cfg_scale, sampler=args.sampler,
                scheduler=args.scheduler, seed=args.seed,
            )
        else:
            source = load_image(args.image)
            mask = load_image(args.mask, mode="L")
            payload = build_inpaint_payload(
                image=source, mask=mask, prompt=args.prompt,
                negative_prompt=args.negative_prompt,
                denoising_strength=args.denoising_strength, mask_blur=args.mask_blur,
                inpainting_mask_invert=0 if args.mask_edit == "white" else 1,
                inpainting_fill=_fill_index(args.masked_content),
                inpaint_full_res=args.inpaint_full_res,
                inpaint_full_res_padding=args.inpaint_full_res_padding,
                steps=args.steps, cfg_scale=args.cfg_scale,
                sampler=args.sampler, scheduler=args.scheduler, seed=args.seed,
            )

        required_model = os.environ.get("FORGE_MODEL", DEFAULT_MODEL)
        status = client.status()
        loaded = status.get("model") or ""
        if required_model and required_model not in loaded:
            raise ForgeError(
                f"Forge has checkpoint '{loaded or 'none'}' loaded; expected '{required_model}'. "
                "Select the checkpoint in Forge before generation; this adapter will not switch models silently."
            )
        free = status.get("cuda_free_mb")
        if free is None:
            raise ForgeError("Forge did not report CUDA free VRAM; refusing to submit an unguarded generation")
        if free < args.min_free_vram_mb:
            raise ForgeError(
                f"Forge reports {free} MiB free VRAM; minimum is {args.min_free_vram_mb} MiB. "
                "No inference was submitted. Release the GPU and retry."
            )
        generation = client.generate(
            args.operation if args.operation == "txt2img" else "img2img",
            payload, minimum_vram_mb=args.min_free_vram_mb, status=status,
        )
        manifest = save_result(
            generation.images, operation=args.operation, payload=payload, status=status,
            out_root=args.out_dir, source=source, mask=mask, requested_model=required_model,
            provider_info=generation.provider_info,
            provider_parameters=generation.provider_parameters,
        )
        print(json.dumps(manifest, indent=2))
        return 0
    except ForgeError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": f"unexpected local adapter error: {exc}"}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
