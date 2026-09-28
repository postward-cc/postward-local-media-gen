#!/usr/bin/env python3
"""Run VibeVoice speech generation through the shared exclusive GPU lease.

Usage:
  python scripts/vibevoice_job.py tts -- --text "Olá, mundo." --seed 431
  python scripts/vibevoice_job.py tts -- --input-file script.txt --speaker-audio 0=voice.wav
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from voice_runtime.client import python_path

QUEUE = ROOT / "scripts" / "job_queue.py"
RUNNER = ROOT / "voice_runtime" / "run.py"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("tts",))
    args, forwarded = parser.parse_known_args(argv)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    if not forwarded:
        parser.error("pass VibeVoice arguments after --")

    python = python_path()
    if not python.is_file():
        parser.error(
            f"VibeVoice runtime not found at {python}; run scripts/bootstrap_vibevoice.sh first"
        )
    command = [
        sys.executable, str(QUEUE), "run", "--kind", "vibevoice-tts", "--",
        str(python), str(RUNNER), args.operation, *forwarded,
    ]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
