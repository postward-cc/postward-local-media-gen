"""Local Forge API adapter. Pure payload builders plus an injectable HTTP seam.

The external interface is intentionally small: `ForgeClient.status()` and
`ForgeClient.generate(payload)`. Image encoding, API dialect, model discovery,
VRAM guards, response decoding and manifest provenance live behind that seam.
No API key is used: this adapter only accepts loopback URLs by default and
never uploads inputs to a hosted service.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

DEFAULT_FORGE_URL = "http://127.0.0.1:7860"
DEFAULT_MIN_FREE_VRAM_MB = 4096
MAX_SIDE = 1280
MAX_PIXELS = 1_310_720
DEFAULT_STEPS = 28
DEFAULT_CFG = 7.0
DEFAULT_SAMPLER = "DPM++ 2M"
DEFAULT_SCHEDULER = "Karras"

class ForgeError(RuntimeError):
    """Safe, user-facing error from the local Forge adapter."""


class ForgeUnavailable(ForgeError):
    pass


class InsufficientVRAM(ForgeError):
    pass


class InvalidInput(ForgeError):
    pass

@dataclass(frozen=True)
class ForgeGeneration:
    images: list[bytes]
    provider_info: str | None
    provider_parameters: dict[str, Any] | None


@dataclass(frozen=True)
class ImageInput:
    path: Path
    data_uri: str
    width: int
    height: int
    sha256: str
    mime_type: str


def loopback_base_url(value: str | None = None) -> str:
    """Return a safe local Forge URL; reject remote hosts to avoid data leaks."""
    raw = (value or os.environ.get("FORGE_URL") or DEFAULT_FORGE_URL).rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme != "http" or not parsed.hostname:
        raise InvalidInput("FORGE_URL must be an http:// loopback URL")
    if parsed.username or parsed.password:
        raise InvalidInput("credentials in FORGE_URL are not supported")
    host = parsed.hostname.lower()
    if host == "localhost":
        return raw
    try:
        if ipaddress.ip_address(host).is_loopback:
            return raw
    except ValueError:
        pass
    raise InvalidInput("Forge adapter refuses remote hosts; inputs must stay local")


def _read_image(path: str | Path, *, mode: str = "RGB") -> ImageInput:
    try:
        from PIL import Image
    except ImportError as exc:
        raise ForgeUnavailable("Pillow is required; run this with Forge's venv Python") from exc

    try:
        source = Path(path).expanduser().resolve(strict=True)
        raw = source.read_bytes()
    except OSError as exc:
        raise InvalidInput(f"input image cannot be read: {path}: {exc}") from exc
    try:
        with Image.open(source) as im:
            im.load()
            width, height = im.size
            converted = im.convert(mode)
            import io
            buffer = io.BytesIO()
            converted.save(buffer, format="PNG", optimize=False)
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception as exc:
        raise InvalidInput(f"not a readable image: {source.name}: {exc}") from exc

    if width < 64 or height < 64:
        raise InvalidInput(f"image is too small ({width}x{height}; minimum 64x64)")
    if width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS:
        raise InvalidInput(
            f"image is {width}x{height}; 8 GB profile limit is {MAX_SIDE}px per side "
            f"and {MAX_PIXELS} pixels. Resize before submission."
        )
    if width % 8 or height % 8:
        raise InvalidInput(f"image dimensions must be multiples of 8; got {width}x{height}")

    return ImageInput(
        path=source,
        data_uri=f"data:image/png;base64,{encoded}",
        width=width,
        height=height,
        sha256=hashlib.sha256(raw).hexdigest(),
        mime_type="image/png",
    )


def prepare_image_pair(image: ImageInput, mask: ImageInput) -> None:
    if (image.width, image.height) != (mask.width, mask.height):
        raise InvalidInput(
            f"mask dimensions {mask.width}x{mask.height} do not match image "
            f"{image.width}x{image.height}"
        )


def build_txt2img_payload(
    *, prompt: str, negative_prompt: str = "", width: int = 1024,
    height: int = 1024, steps: int = DEFAULT_STEPS, cfg_scale: float = DEFAULT_CFG,
    sampler: str = DEFAULT_SAMPLER, scheduler: str = DEFAULT_SCHEDULER,
    seed: int = -1,
) -> dict[str, Any]:
    _validate_generation(prompt, width, height, steps, cfg_scale)
    return {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "cfg_scale": cfg_scale,
        "sampler_name": sampler,
        "scheduler": scheduler,
        "seed": seed,
        "batch_size": 1,
        "n_iter": 1,
        "send_images": True,
        "save_images": False,
    }


def build_img2img_payload(
    *, image: ImageInput, prompt: str, negative_prompt: str = "",
    denoising_strength: float = 0.55, steps: int = DEFAULT_STEPS,
    cfg_scale: float = DEFAULT_CFG, sampler: str = DEFAULT_SAMPLER,
    scheduler: str = DEFAULT_SCHEDULER, seed: int = -1,
) -> dict[str, Any]:
    _validate_generation(prompt, image.width, image.height, steps, cfg_scale)
    _validate_denoising(denoising_strength)
    return {
        "init_images": [image.data_uri],
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "width": image.width,
        "height": image.height,
        "denoising_strength": denoising_strength,
        "steps": steps,
        "cfg_scale": cfg_scale,
        "sampler_name": sampler,
        "scheduler": scheduler,
        "seed": seed,
        "batch_size": 1,
        "n_iter": 1,
        "send_images": True,
        "save_images": False,
    }


def build_inpaint_payload(
    *, image: ImageInput, mask: ImageInput, prompt: str, negative_prompt: str = "",
    denoising_strength: float = 0.45, mask_blur: int = 4,
    inpainting_mask_invert: int = 0, inpainting_fill: int = 1,
    inpaint_full_res: bool = False, inpaint_full_res_padding: int = 32,
    steps: int = DEFAULT_STEPS, cfg_scale: float = DEFAULT_CFG,
    sampler: str = DEFAULT_SAMPLER, scheduler: str = DEFAULT_SCHEDULER,
    seed: int = -1,
) -> dict[str, Any]:
    """White mask pixels are edited; black pixels are protected (Forge default)."""
    prepare_image_pair(image, mask)
    _validate_generation(prompt, image.width, image.height, steps, cfg_scale)
    _validate_denoising(denoising_strength)
    if not 0 <= mask_blur <= 64:
        raise InvalidInput("mask_blur must be between 0 and 64 pixels")
    if inpainting_mask_invert not in (0, 1):
        raise InvalidInput("mask inversion must be 0 (white edits) or 1 (black edits)")
    if inpainting_fill not in (0, 1, 2, 3):
        raise InvalidInput("inpainting_fill must be 0=fill, 1=original, 2=latent noise, or 3=latent nothing")
    return {
        "init_images": [image.data_uri],
        "mask": mask.data_uri,
        "inpainting_mask_invert": inpainting_mask_invert,
        "inpainting_fill": inpainting_fill,
        "mask_blur": mask_blur,
        "inpaint_full_res": inpaint_full_res,
        "inpaint_full_res_padding": inpaint_full_res_padding,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "width": image.width,
        "height": image.height,
        "denoising_strength": denoising_strength,
        "steps": steps,
        "cfg_scale": cfg_scale,
        "sampler_name": sampler,
        "scheduler": scheduler,
        "seed": seed,
        "batch_size": 1,
        "n_iter": 1,
        "send_images": True,
        "save_images": False,
    }


def _validate_generation(prompt: str, width: int, height: int, steps: int, cfg: float) -> None:
    if not prompt.strip():
        raise InvalidInput("prompt cannot be empty")
    if width < 64 or height < 64 or width > MAX_SIDE or height > MAX_SIDE:
        raise InvalidInput(f"width and height must be 64..{MAX_SIDE} pixels for the 8 GB profile")
    if width % 8 or height % 8:
        raise InvalidInput("width and height must be multiples of 8")
    if width * height > MAX_PIXELS:
        raise InvalidInput(f"resolution exceeds the 8 GB profile limit ({MAX_PIXELS} pixels)")
    if not 1 <= steps <= 60:
        raise InvalidInput("steps must be between 1 and 60")
    if not 1 <= cfg <= 30:
        raise InvalidInput("cfg_scale must be between 1 and 30")


def _validate_denoising(value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise InvalidInput("denoising_strength must be between 0.0 and 1.0")


def _decode_image(value: str) -> bytes:
    if value.startswith("data:"):
        try:
            value = value.split(",", 1)[1]
        except IndexError as exc:
            raise ForgeError("Forge returned malformed image data URI") from exc
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:
        raise ForgeError("Forge returned invalid base64 image data") from exc


class ForgeClient:
    """Local Forge API client. `transport` is injectable for deterministic tests."""

    def __init__(
        self, base_url: str | None = None, timeout: int = 30,
        transport: Callable[[str, str, dict | None, int], Any] | None = None,
    ):
        self.base_url = loopback_base_url(base_url)
        self.timeout = timeout
        self.transport = transport or self._urllib_transport

    @staticmethod
    def _urllib_transport(method: str, url: str, payload: dict | None, timeout: int) -> Any:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise ForgeError(f"Forge HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ForgeUnavailable(f"Forge is unreachable at {url}: {exc}") from exc
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ForgeError(f"Forge returned invalid JSON from {url}") from exc

    def get(self, endpoint: str) -> Any:
        return self.transport("GET", self.base_url + endpoint, None, self.timeout)

    def post(self, endpoint: str, payload: dict) -> Any:
        return self.transport("POST", self.base_url + endpoint, payload, max(self.timeout, 600))

    def status(self) -> dict[str, Any]:
        """Read-only health/model/VRAM probe. Does not start inference or load a model."""
        options = self.get("/sdapi/v1/options")
        models = self.get("/sdapi/v1/sd-models")
        memory = self.get("/sdapi/v1/memory")
        current = options.get("sd_model_checkpoint") if isinstance(options, dict) else None
        model_records = [item for item in models if isinstance(item, dict)] if isinstance(models, list) else []
        selected = next(
            (
                item for item in model_records
                if current and (current == item.get("title") or current in (item.get("title") or ""))
            ),
            None,
        )
        model_names = [item.get("model_name") or item.get("title") for item in model_records]
        cuda = memory.get("cuda", {}) if isinstance(memory, dict) else {}
        system = cuda.get("system", {}) if isinstance(cuda, dict) else {}
        free_bytes = system.get("free") if isinstance(system, dict) else None
        total_bytes = system.get("total") if isinstance(system, dict) else None
        return {
            "available": True,
            "base_url": self.base_url,
            "model": current,
            "model_sha256": selected.get("sha256") if selected else None,
            "model_filename": selected.get("filename") if selected else None,
            "models": model_names,
            "cuda_free_mb": int(free_bytes / 1024 / 1024) if isinstance(free_bytes, (int, float)) else None,
            "cuda_total_mb": int(total_bytes / 1024 / 1024) if isinstance(total_bytes, (int, float)) else None,
            "memory": memory,
        }
    def require_vram(self, minimum_mb: int | None = None) -> dict[str, Any]:
        threshold = minimum_mb if minimum_mb is not None else int(
            os.environ.get("FORGE_MIN_FREE_VRAM_MB", str(DEFAULT_MIN_FREE_VRAM_MB))
        )
        status = self.status()
        free = status.get("cuda_free_mb")
        if free is None:
            raise ForgeUnavailable("Forge did not report CUDA free memory; refusing to risk an unguarded OOM")
        if free < threshold:
            raise InsufficientVRAM(
                f"Forge has {free} MiB free VRAM; this operation requires at least {threshold} MiB. "
                "Free the GPU and retry; no inference was submitted."
            )
        return status

    def generate(
        self, operation: str, payload: dict, *, minimum_vram_mb: int | None = None,
        status: dict[str, Any] | None = None,
    ) -> ForgeGeneration:
        if operation not in {"txt2img", "img2img"}:
            raise InvalidInput(f"unsupported Forge operation: {operation}")
        # Reuse the fresh preflight status when caller has it; otherwise guard
        # this module's own call before reaching the expensive endpoint.
        if status is None:
            self.require_vram(minimum_vram_mb)
        elif status.get("cuda_free_mb") is None:
            raise ForgeUnavailable("Forge did not report CUDA free memory")
        elif status["cuda_free_mb"] < (
            minimum_vram_mb if minimum_vram_mb is not None else DEFAULT_MIN_FREE_VRAM_MB
        ):
            raise InsufficientVRAM(
                f"Forge has {status['cuda_free_mb']} MiB free VRAM; "
                f"minimum is {minimum_vram_mb if minimum_vram_mb is not None else DEFAULT_MIN_FREE_VRAM_MB} MiB"
            )
        response = self.post(f"/sdapi/v1/{operation}", payload)
        images = response.get("images") if isinstance(response, dict) else None
        if not isinstance(images, list) or not images:
            raise ForgeError("Forge returned no images")
        parameters = response.get("parameters") if isinstance(response, dict) else None
        info = response.get("info") if isinstance(response, dict) else None
        return ForgeGeneration(
            images=[_decode_image(item) for item in images],
            provider_info=info if isinstance(info, str) else None,
            provider_parameters=parameters if isinstance(parameters, dict) else None,
        )


def load_image(path: str | Path, *, mode: str = "RGB") -> ImageInput:
    return _read_image(path, mode=mode)
