"""Lossless local composition of a model edit into a protected source image."""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter


class CompositionError(ValueError):
    """Safe, user-facing validation error for masked image composition."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(data)
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def composite_masked_edit(
    base_path: str | Path,
    edit_path: str | Path,
    mask_path: str | Path,
    output_path: str | Path,
    *,
    feather_radius: float = 0,
    manifest_path: str | Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Composite only mask-authorized pixels from ``edit`` onto ``base``.

    White mask pixels select the edited image; black pixels preserve the base;
    gray pixels blend. A Gaussian feather is applied to the mask, not the
    image. The output is always lossless PNG so the protected-area invariant can
    be checked exactly after saving.
    """
    if not math.isfinite(feather_radius) or feather_radius < 0:
        raise CompositionError("feather radius must be a finite non-negative number")

    base = Path(base_path).expanduser().resolve(strict=True)
    edit = Path(edit_path).expanduser().resolve(strict=True)
    mask = Path(mask_path).expanduser().resolve(strict=True)
    output = Path(output_path).expanduser().resolve()
    manifest = (
        Path(manifest_path).expanduser().resolve()
        if manifest_path is not None
        else output.with_suffix(".manifest.json")
    )

    if output.suffix.lower() != ".png":
        raise CompositionError("output must be PNG to preserve pixels losslessly")
    if output in {base, edit, mask} or manifest in {base, edit, mask, output}:
        raise CompositionError("output and manifest paths must not overwrite an input")
    if not overwrite and (output.exists() or manifest.exists()):
        raise CompositionError("output or manifest already exists; pass overwrite=True to replace it")

    try:
        with Image.open(base) as image:
            base_image = image.convert("RGBA")
        with Image.open(edit) as image:
            edit_image = image.convert("RGBA")
        with Image.open(mask) as image:
            edit_mask = image.convert("L")
    except (OSError, ValueError) as exc:
        raise CompositionError(f"could not read base, edit, or mask image: {exc}") from exc

    size = base_image.size
    if edit_image.size != size or edit_mask.size != size:
        raise CompositionError(
            "base, edit, and mask dimensions must match exactly; "
            f"got base={size}, edit={edit_image.size}, mask={edit_mask.size}"
        )

    if feather_radius:
        edit_mask = edit_mask.filter(ImageFilter.GaussianBlur(radius=feather_radius))

    result = Image.composite(edit_image, base_image, edit_mask)
    buffer = BytesIO()
    result.save(buffer, format="PNG")
    output_bytes = buffer.getvalue()

    # Re-open the encoded PNG; do not claim exactness based only on an in-memory
    # image before serialization.

    with Image.open(BytesIO(output_bytes)) as saved_image:
        saved = saved_image.convert("RGBA")
    difference = ImageChops.difference(base_image, saved)
    protected_mask = Image.eval(edit_mask, lambda value: 255 if value == 0 else 0)
    outside_difference = ImageChops.multiply(difference, protected_mask.convert("RGBA"))
    protected_pixels_exact = outside_difference.getbbox() is None
    if not protected_pixels_exact:
        raise CompositionError("protected pixels changed during composition")

    editable_histogram = edit_mask.histogram()
    manifest_data = {
        "schema_version": 1,
        "status": "success",
        "operation": "masked-image-composition",
        "mask_semantics": "white=editable, black=protected, gray=blend",
        "feather_radius": feather_radius,
        "dimensions": {"width": size[0], "height": size[1]},
        "base": {"path": str(base), "sha256": _sha256(base)},
        "edit": {"path": str(edit), "sha256": _sha256(edit)},
        "mask": {"path": str(mask), "sha256": _sha256(mask)},
        "output": {"path": str(output), "sha256": hashlib.sha256(output_bytes).hexdigest()},
        "editable_pixel_count": sum(editable_histogram[1:]),
        "protected_pixels_exact": protected_pixels_exact,
        "manifest_path": str(manifest),
    }
    _atomic_write(output, output_bytes)
    _atomic_write(manifest, (json.dumps(manifest_data, indent=2) + "\n").encode())
    return manifest_data
