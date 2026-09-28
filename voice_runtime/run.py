#!/usr/bin/env python3
"""Status, prepare and locally queued TTS for VibeVoice 1.5B."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from voice_runtime.client import (
    AUTO_GPU_MEMORY_GIB,
    MIN_FREE_VRAM_MB,
    MODEL_ID,
    MODEL_REVISION,
    SOURCE_REVISION,
    InvalidInput,
    VoiceError,
    generate_audio,
    hf_home,
    home_dir,
    model_snapshot_path,
    parse_script,
    parse_speaker_audio,
    python_path,
    sha256_file,
    source_dir,
)

DEFAULT_OUTPUT = ROOT / "voice_runtime" / "outputs"


def _existing_filesystem_path(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate
MIN_MODEL_FREE_DISK_BYTES = 12 * 1024**3


def _require_research_ok() -> None:
    if os.environ.get("VIBEVOICE_RESEARCH_OK") != "1":
        raise VoiceError(
            "VibeVoice model cards limit intended use to research and development. "
            "Review the model card, then set VIBEVOICE_RESEARCH_OK=1 for this invocation."
        )


def _dependency_status() -> dict[str, Any]:
    python = python_path()
    if not python.is_file():
        return {"available": False, "python": str(python), "missing": ["runtime venv"]}
    probe = (
        "import json, torch, transformers, diffusers, accelerate, soundfile; "
        "from transformers import AutoModelForTextToWaveform, AutoProcessor; "
        "ok=torch.cuda.is_available(); free,total=torch.cuda.mem_get_info() if ok else (0,0); "
        "print(json.dumps({'torch':torch.__version__,'transformers':transformers.__version__,"
        "'diffusers':diffusers.__version__,'accelerate':accelerate.__version__,"
        "'soundfile':soundfile.__version__,'cuda':ok,"
        "'cuda_free_mb':int(free/1048576) if ok else None,"
        "'cuda_total_mb':int(total/1048576) if ok else None,"
        "'vibevoice_class':AutoModelForTextToWaveform.__name__}))"
    )
    result = subprocess.run([str(python), "-c", probe], text=True, capture_output=True, check=False)
    if result.returncode:
        return {
            "available": False,
            "python": str(python),
            "missing_or_broken": result.stderr.strip().splitlines()[-1:] or ["dependency probe failed"],
        }
    try:
        versions = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"available": False, "python": str(python), "missing_or_broken": ["invalid probe output"]}
    return {"available": versions["transformers"] == "5.17.0" and versions["cuda"],
            "python": str(python), **versions}


def _source_status() -> dict[str, Any]:
    source = source_dir()
    if not (source / ".git").is_dir():
        return {"present": False, "path": str(source), "revision_matches": False}
    result = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        text=True, capture_output=True, check=False,
    )
    revision = result.stdout.strip() if result.returncode == 0 else None
    voices = source / "demo" / "voices"
    return {
        "present": True,
        "path": str(source),
        "revision": revision,
        "revision_matches": revision == SOURCE_REVISION,
        "voice_samples": len(list(voices.glob("*.wav"))) if voices.is_dir() else 0,
    }


def status_data() -> dict[str, Any]:
    snapshot = model_snapshot_path()
    cached = (
        snapshot.is_dir()
        and (snapshot / "config.json").is_file()
        and (snapshot / "model.safetensors.index.json").is_file()
        and all((snapshot / f"model-0000{index}-of-00003.safetensors").is_file() for index in range(1, 4))
    )
    filesystem = _existing_filesystem_path(home_dir())
    try:
        free_disk_gb = round(shutil.disk_usage(filesystem).free / 1024**3, 1)
    except OSError:
        free_disk_gb = None
    dependencies = _dependency_status()
    source = _source_status()
    enough_vram = (
        dependencies.get("cuda_free_mb") is not None
        and dependencies["cuda_free_mb"] >= MIN_FREE_VRAM_MB
    )
    return {
        "ready": dependencies["available"] and enough_vram and cached and source["revision_matches"],
        "enough_free_vram": enough_vram,
        "minimum_free_vram_mb": MIN_FREE_VRAM_MB,
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "model_cached": cached,
        "model_path": str(snapshot) if cached else None,
        "home": str(home_dir()),
        "hf_cache": str(hf_home()),
        "source": source,
        "dependencies": dependencies,
        "free_disk_gb": free_disk_gb,
        "gpu_lock": "comfyui-runtime/state/gpu.lock",
        "network_downloads": "only the explicit prepare command downloads model weights",
    }


def prepare_model() -> dict[str, Any]:
    _require_research_ok()
    python = python_path()
    if not python.is_file():
        raise VoiceError(f"VibeVoice runtime is not installed: {python}. Run scripts/bootstrap_vibevoice.sh.")
    filesystem = _existing_filesystem_path(home_dir())
    free_bytes = shutil.disk_usage(filesystem).free
    if free_bytes < MIN_MODEL_FREE_DISK_BYTES:
        raise VoiceError(
            f"Only {free_bytes / 1024**3:.1f} GiB are free under {filesystem}; "
            f"the model download requires at least {MIN_MODEL_FREE_DISK_BYTES / 1024**3:.0f} GiB free."
        )
    code = (
        "import json; from huggingface_hub import snapshot_download; "
        f"p=snapshot_download(repo_id={MODEL_ID!r}, revision={MODEL_REVISION!r}, "
        f"cache_dir={str(hf_home() / 'hub')!r}); "
        "print(json.dumps({'model_path':p}))"
    )
    env = os.environ.copy()
    env["VIBEVOICE_HOME"] = str(home_dir())
    env["HF_HOME"] = str(hf_home())
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    result = subprocess.run([str(python), "-c", code], cwd=ROOT, env=env, check=False)
    if result.returncode:
        raise VoiceError("Hugging Face model download failed; see the preceding downloader error.")
    return {"model_id": MODEL_ID, "revision": MODEL_REVISION, "model_path": str(model_snapshot_path())}


def _job_id() -> str:
    candidate = os.environ.get("POSTWARD_JOB_ID") or (
        f"vibevoice-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    )
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", candidate):
        raise VoiceError("invalid POSTWARD_JOB_ID")
    return candidate


def _read_script(args: argparse.Namespace) -> tuple[str, str | None]:
    if args.text is not None:
        text = args.text
        source_path = None
    else:
        path = args.input_file.expanduser().resolve(strict=True)
        if not path.is_file():
            raise InvalidInput(f"script is not a file: {path}")
        text = path.read_text(encoding="utf-8")
        source_path = str(path)
    parse_script(text)
    return text, source_path


def run_tts(args: argparse.Namespace) -> dict[str, Any]:
    _require_research_ok()
    if os.environ.get("POSTWARD_GPU_LOCK_HELD") != "1":
        raise VoiceError(
            "VibeVoice GPU inference must run under the shared GPU lease. "
            "Use `python scripts/vibevoice_job.py tts -- ...`."
        )
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    snapshot = model_snapshot_path()
    if not snapshot.is_dir():
        raise VoiceError(f"model weights are not cached. Run `python voice_runtime/run.py prepare` first.")
    dependencies = _dependency_status()
    if not dependencies["available"]:
        raise VoiceError(
            "VibeVoice runtime dependencies are missing or incompatible. "
            "Run `scripts/bootstrap_vibevoice.sh` and check `python voice_runtime/run.py status`."
        )
    free_vram_mb = dependencies.get("cuda_free_mb")
    if free_vram_mb is None or free_vram_mb < MIN_FREE_VRAM_MB:
        raise VoiceError(
            f"VibeVoice requires at least {MIN_FREE_VRAM_MB} MiB free VRAM to keep "
            f"the diffusion head on the GPU; measured {free_vram_mb} MiB."
        )
    if not 32 <= args.max_new_tokens <= 4096:
        raise InvalidInput("max-new-tokens must be between 32 and 4096")

    text, source_path = _read_script(args)
    turns = parse_script(text)
    references = parse_speaker_audio(args.speaker_audio)
    output_root = args.output_root.expanduser() if args.output_root else DEFAULT_OUTPUT
    folder = output_root / _job_id()
    folder.mkdir(parents=True, exist_ok=False)
    output = folder / "speech.wav"
    try:
        sample_rate = generate_audio(
            model_path=snapshot,
            turns=turns,
            speaker_audio=references,
            output_path=output,
            seed=args.seed,
            max_new_tokens=args.max_new_tokens,
        )
        result = {
            "job_id": folder.name,
            "status": "success",
            "local_inference": True,
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "vibevoice_source_revision": _source_status().get("revision"),
            "script_path": source_path,
            "script_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "speakers": sorted({turn.speaker for turn in turns}),
            "voice_references": {
                speaker: {"path": str(path), "sha256": sha256_file(path)}
                for speaker, path in references.items()
            },
            "settings": {
                "seed": args.seed,
                "max_new_tokens": args.max_new_tokens,
                "max_gpu_memory_gib": AUTO_GPU_MEMORY_GIB,
                "minimum_free_vram_mb": MIN_FREE_VRAM_MB,
                "dtype": "bfloat16",
                "device_map": "auto",
            },
            "output": {
                "path": str(output.resolve()),
                "sample_rate": sample_rate,
                "bytes": output.stat().st_size,
                "sha256": sha256_file(output),
            },
        }
        manifest = folder / "manifest.json"
        manifest.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        result["manifest"] = str(manifest.resolve())
        return result
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("status", help="check runtime, model cache and source checkout without inference")
    sub.add_parser("prepare", help="download the pinned model weights into the configured data cache")

    tts = sub.add_parser("tts", help="generate WAV speech from text or a speaker-labeled script")
    source = tts.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="short single-speaker text")
    source.add_argument("--input-file", type=Path, help="UTF-8 text; optional Speaker 0..3: labels")
    tts.add_argument(
        "--speaker-audio", action="append", default=[], metavar="ID=PATH",
        help="local consented reference WAV for a speaker, repeat for multiple speakers",
    )
    tts.add_argument("--seed", type=int, default=431)
    tts.add_argument("--max-new-tokens", type=int, default=400)
    tts.add_argument("--output-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.operation == "status":
            result = status_data()
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result["ready"] else 1
        if args.operation == "prepare":
            print(json.dumps(prepare_model(), indent=2, ensure_ascii=False))
            return 0
        result = run_tts(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (VoiceError, OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
