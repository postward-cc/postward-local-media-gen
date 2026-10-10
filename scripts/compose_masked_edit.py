#!/usr/bin/env python3
"""Composite a local model edit only inside a white mask; save a PNG manifest."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forge_runtime.masked_composition import CompositionError, composite_masked_edit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="canonical source image")
    parser.add_argument("--edit", required=True, help="model-edited image, same dimensions")
    parser.add_argument("--mask", required=True, help="white=editable, black=protected, gray=blend")
    parser.add_argument("--out", required=True, help="lossless PNG output path")
    parser.add_argument(
        "--manifest", help="sidecar JSON path; default is <out stem>.manifest.json"
    )
    parser.add_argument("--feather", type=float, default=0, help="Gaussian mask feather radius in pixels")
    parser.add_argument("--overwrite", action="store_true", help="replace existing output and manifest")
    args = parser.parse_args(argv)

    try:
        manifest = composite_masked_edit(
            args.base,
            args.edit,
            args.mask,
            args.out,
            feather_radius=args.feather,
            manifest_path=args.manifest,
            overwrite=args.overwrite,
        )
    except (CompositionError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2

    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
