#!/usr/bin/env python3
"""Run a local Forge generation through the repository's exclusive GPU lease.

Usage:
  python scripts/forge_job.py txt2img -- --prompt "..." --out-dir /path
  python scripts/forge_job.py img2img -- --image ref.png --prompt "..."
  python scripts/forge_job.py inpaint -- --image ref.png --mask ears.png --prompt "..."

The wrapper delegates to `job_queue.py run`, so Forge and ComfyUI/H3 contend on
exactly one flock. It never starts/stops a known service and never shells through
user prompt text.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "scripts" / "job_queue.py"
FORGE_RUNNER = ROOT / "forge_runtime" / "run.py"
def forge_python() -> Path:
    configured = os.environ.get("FORGE_PYTHON")
    if configured:
        return Path(configured).expanduser()
    forge_home = os.environ.get("FORGE_HOME")
    candidates = []
    if forge_home:
        candidates.append(Path(forge_home).expanduser() / "venv" / "bin" / "python")
    candidates.append(ROOT / "comfyui-runtime" / "venv" / "bin" / "python")
    return next((path for path in candidates if path.is_file()), Path(sys.executable))


def build_queue_command(operation: str, forwarded: list[str], forge_python: str | Path) -> list[str]:
    if operation not in {"txt2img", "img2img", "inpaint"}:
        raise ValueError(f"unsupported Forge operation: {operation}")
    return [
        sys.executable, str(QUEUE), "run", "--kind", f"forge-{operation}", "--",
        str(forge_python), str(FORGE_RUNNER), operation, *forwarded,
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("txt2img", "img2img", "inpaint"))
    args, forwarded = parser.parse_known_args(argv)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    if not forwarded:
        parser.error("pass the Forge operation arguments after --")

    python = forge_python()
    if not python.is_file():
        parser.error(f"configured Python interpreter does not exist: {python}")
    command = build_queue_command(args.operation, forwarded, python)
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
