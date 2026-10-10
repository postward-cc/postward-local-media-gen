#!/usr/bin/env python3
"""Detect local media-generation capabilities and recommend a profile."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = ROOT / "comfyui-runtime"

from forge_runtime.client import DEFAULT_FORGE_URL, DEFAULT_MIN_FREE_VRAM_MB, ForgeClient, ForgeError
from voice_runtime.client import home_dir as vibevoice_home, python_path as vibevoice_python
from voice_runtime.run import status_data as vibevoice_info


def command(*args: str, timeout: int = 15) -> str | None:
    try:
        return subprocess.check_output(
            args, text=True, stderr=subprocess.STDOUT, timeout=timeout
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


#: Tools this skill may invoke when no repository adapter covers the step. The
#: key is the tool id used in ``doctor.py`` output and in SKILL.md; the flag is
#: the one that makes that tool print a version. Probing must never be fatal:
#: a missing tool is reported, not raised.
EXTERNAL_TOOLS: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    ("ffmpeg", "video", "FFmpeg", "-version", ("ffmpeg",)),
    ("ffprobe", "video", "FFmpeg", "-version", ("ffprobe",)),
    ("imagemagick", "raster", "ImageMagick", "--version", ("magick", "convert")),
    ("graphicsmagick", "raster", "GraphicsMagick", "version", ("gm",)),
    ("libvips", "raster", "libvips", "--version", ("vips",)),
    ("gmic", "filter", "G'MIC", "--version", ("gmic",)),
    ("openimageio", "filter", "OpenImageIO", "--help", ("oiiotool",)),
    ("gimp", "raster", "GIMP", "--version", ("gimp-console",)),
    ("inkscape", "vector", "Inkscape", "--version", ("inkscape",)),
    ("qpdf", "pdf", "qpdf", "--version", ("qpdf",)),
    ("ghostscript", "pdf", "Ghostscript", "--version", ("gs",)),
    ("darktable", "raw", "darktable", "--version", ("darktable-cli",)),
    ("rawtherapee", "raw", "RawTherapee", "--version", ("rawtherapee-cli",)),
    ("exiftool", "metadata", "ExifTool", "-ver", ("exiftool",)),
    ("docker", "sidecar", "Docker", "--version", ("docker",)),
)


def external_tool_info(tools: tuple = EXTERNAL_TOOLS) -> dict:
    """Report which external local tools exist and at which version.

    A tool that is absent, or that fails to report a version, is recorded as
    unavailable; it is never an error. This is the evidence behind the tool
    preference order in SKILL.md: an agent must not assume a local tool is
    installed.
    """
    report: dict = {}
    for key, capability, name, version_flag, candidates in tools:
        path = next((p for p in (shutil.which(c) for c in candidates) if p), None)
        entry = {
            "capability": capability,
            "name": name,
            "command": candidates[0],
            "path": path,
            "available": path is not None,
            "version": None,
        }
        if path is not None:
            printed = command(path, version_flag, timeout=10)
            if printed:
                entry["version"] = printed.splitlines()[0][:200]
        report[key] = entry
    return report


def memory_gb() -> float | None:
    try:
        data = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            data[key] = int(value.strip().split()[0])
        return round(data["MemTotal"] / 1024 / 1024, 1)
    except (OSError, KeyError, ValueError):
        return None


#: Interpreter range this repository supports, and the version its bootstrap
#: pins. ``uv`` manages that interpreter, so an existing venv survives a system
#: Python upgrade; a venv created by ``python -m venv`` does not.
PYTHON_MIN = (3, 11)
PYTHON_MAX = (3, 14)
PINNED_PYTHON_VERSION = "3.12"

#: CUDA build tag the pinned PyTorch index publishes. A torch wheel without it
#: installs cleanly and only fails at inference time, with a missing-kernel
#: error far away from its cause, so the lock is checked before it is trusted.
EXPECTED_CUDA_TAG = "cu128"
CUDA_WHEEL_PACKAGES = ("torch", "torchvision", "torchaudio")


def cuda_tag_problems(lock_text: str, expected: str = EXPECTED_CUDA_TAG) -> list[str]:
    """Report torch-family entries in a requirements lock without the CUDA tag.

    Index ordering during resolution decides whether torch comes from PyPI or
    from the PyTorch CUDA index, and getting it backwards is silent. This turns
    that decision into a check.
    """
    problems = []
    for package in CUDA_WHEEL_PACKAGES:
        for match in re.finditer(rf"^{package}==(\S+)", lock_text, re.MULTILINE):
            version = match.group(1).rstrip("\\").strip()
            if not version.endswith(f"+{expected}"):
                problems.append(
                    f"{package}=={version} lacks the +{expected} CUDA build"
                )
    return problems


def lock_pins(lock_text: str) -> dict[str, str]:
    """Extract ``name -> version`` from a ``uv pip compile`` requirements lock."""
    pins = {}
    for line in lock_text.splitlines():
        match = re.match(r"^([A-Za-z0-9._-]+)==([^\s\\]+)", line)
        if match:
            pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pins


def env_drift(lock_text: str, installed: dict[str, str]) -> dict:
    """Compare an environment against its lock.

    ``installed`` maps distribution names to versions. Mismatched and missing
    packages are reported separately: a stale environment is a different
    problem from one that was never installed.
    """
    pins = lock_pins(lock_text)
    normalized = {k.lower().replace("_", "-"): v for k, v in installed.items()}
    mismatched = [
        {"package": name, "locked": version, "installed": normalized.get(name)}
        for name, version in sorted(pins.items())
        if name in normalized and normalized[name] != version
    ]
    missing = [
        {"package": name, "locked": version}
        for name, version in sorted(pins.items())
        if name not in normalized
    ]
    return {
        "locked_packages": len(pins),
        "installed_packages": len(normalized),
        "mismatched": mismatched,
        "missing": missing,
        "in_sync": not mismatched and not missing,
    }


def installed_distributions(python: Path) -> dict[str, str] | None:
    """List distribution versions inside an environment, or None if unusable."""
    probe = (
        "import json;"
        "from importlib.metadata import distributions;"
        "print(json.dumps({d.metadata['Name'].lower(): d.version"
        " for d in distributions() if d.metadata['Name']}))"
    )
    raw = command(str(python), "-c", probe, timeout=60)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def environment_drift(lock: Path, python: Path) -> dict:
    """Drift of one environment against one lock, plus the reason if unknown."""
    if not lock.exists():
        return {"status": "no-lock", "lock": str(lock)}
    if not python.exists() or not os.access(python, os.X_OK):
        return {"status": "no-environment", "lock": str(lock),
                "python": str(python)}
    installed = installed_distributions(python)
    if installed is None:
        return {"status": "unreadable-environment", "lock": str(lock),
                "python": str(python)}
    report = env_drift(lock.read_text(), installed)
    report["status"] = "in-sync" if report["in_sync"] else "drifted"
    report["lock"] = str(lock)
    report["python"] = str(python)
    return report


def check_lock(path: str) -> int:
    """``doctor.py check-lock <file>``: exit non-zero on an unusable lock."""
    try:
        text = Path(path).read_text()
    except OSError as exc:
        print(json.dumps({"lock": path, "error": str(exc)}))
        return 2
    problems = cuda_tag_problems(text)
    print(json.dumps({"lock": path, "expected_cuda_tag": EXPECTED_CUDA_TAG,
                      "problems": problems}, indent=2))
    return 1 if problems else 0


def python_runtime_info(venv: Path = RUNTIME / "venv") -> dict:
    """Report the interpreter running doctor and the pinned runtime venv.

    A venv whose interpreter no longer exists — the usual symptom of a system
    Python upgrade — is reported as broken rather than raising.
    """
    venv_python = venv / "bin" / "python"
    return {
        "doctor_python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "doctor_python_in_range": PYTHON_MIN <= sys.version_info[:2] < PYTHON_MAX,
        "pinned_version": PINNED_PYTHON_VERSION,
        "venv_python": str(venv_python),
        "venv_python_exists": venv_python.exists(),
        "venv_python_usable": os.access(venv_python, os.X_OK),
        "venv_python_version": command(str(venv_python), "-V"),
    }


def torch_info() -> dict:
    """Probe the runtime venv, even when doctor runs from system Python."""
    probe = RUNTIME / "venv" / "bin" / "python"
    if not probe.exists():
        probe = Path(sys.executable)
    code = (
        "import json, torch; "
        "ok=torch.cuda.is_available(); "
        "p=torch.cuda.get_device_properties(0) if ok else None; "
        "print(json.dumps({'available':ok,'torch':torch.__version__,"
        "'compiled_cuda':torch.version.cuda,"
        "'gpu':p.name if p else None,"
        "'vram_gb':round(p.total_memory/1024**3,2) if p else None,"
        "'vram_mb':round(p.total_memory/1024**2) if p else None,"
        "'compute_capability':list(torch.cuda.get_device_capability(0)) if p else None}))"
    )
    try:
        return json.loads(subprocess.check_output([str(probe), "-c", code], text=True))
    except Exception as exc:
        return {"available": False, "python": str(probe), "error": str(exc)}


def forge_info(client_factory=ForgeClient) -> dict:
    """Report Forge install/API/model/free VRAM without submitting inference."""
    configured_home = os.environ.get("FORGE_HOME")
    home = Path(configured_home).expanduser() if configured_home else None
    required_model = os.environ.get("FORGE_MODEL", "sd_xl_base_1.0.safetensors")
    checkpoint_value = os.environ.get("FORGE_CHECKPOINT_PATH")
    checkpoint = (
        Path(checkpoint_value).expanduser()
        if checkpoint_value
        else home / "models" / "Stable-diffusion" / required_model
        if home
        else None
    )
    url = os.environ.get("FORGE_URL", DEFAULT_FORGE_URL)
    minimum_free = int(os.environ.get("FORGE_MIN_FREE_VRAM_MB", str(DEFAULT_MIN_FREE_VRAM_MB)))
    install = {
        "configured": home is not None,
        "home": str(home) if home else None,
        "launcher_present": bool(home and (home / "webui.sh").is_file()),
        "checkpoint_path": str(checkpoint) if checkpoint else None,
        "checkpoint_present": bool(checkpoint and checkpoint.is_file()),
    }
    try:
        status = client_factory(url).status()
    except ForgeError as exc:
        return {
            "installed": install["launcher_present"] and install["checkpoint_present"],
            "installation": install,
            "available": False,
            "url": url,
            "required_model": required_model,
            "minimum_free_vram_mb": minimum_free,
            "can_generate": False,
            "error": str(exc),
        }

    loaded = status.get("model") or ""
    model_loaded = required_model in loaded
    free = status.get("cuda_free_mb")
    enough_vram = free is not None and free >= minimum_free
    return {
        "installed": install["launcher_present"] and install["checkpoint_present"],
        "installation": install,
        "available": True,
        "url": url,
        "required_model": required_model,
        "loaded_model": loaded,
        "loaded_model_filename": status.get("model_filename"),
        "loaded_model_sha256": status.get("model_sha256"),
        "model_loaded": model_loaded,
        "available_models": status.get("models", []),
        "free_vram_mb": free,
        "minimum_free_vram_mb": minimum_free,
        "can_generate": model_loaded and enough_vram,
        "memory": status.get("memory"),
    }

def vibevoice_environment() -> dict:
    """Drift of the speech runtime against its lock."""
    report = environment_drift(ROOT / "requirements-vibevoice.lock",
                                vibevoice_python())
    report["home"] = str(vibevoice_home())
    return report


def main() -> int:
    if sys.argv[1:2] == ["check-lock"]:
        if len(sys.argv) != 3:
            print("usage: doctor.py check-lock <requirements.lock>")
            return 2
        return check_lock(sys.argv[2])
    gpu_query = command(
        "nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version",
        "--format=csv,noheader,nounits",
    )
    gpu = None
    if gpu_query:
        parts = [part.strip() for part in gpu_query.split(",", 3)]
        if len(parts) == 4:
            gpu = {"name": parts[0], "vram_mb": int(parts[1]),
                   "free_vram_mb": int(parts[2]), "driver": parts[3]}

    torch = torch_info()
    total_mb = int(torch.get("vram_mb") or (gpu or {}).get("vram_mb", 0))
    if total_mb < 7800:
        profile = "constrained: do not use the official 8 GB H3 profile"
    elif total_mb < 12000:
        profile = "4060-8gb: INT8+NVFP4, lowvram, 0.2-0.4 MP, one GPU job"
    elif total_mb < 16000:
        profile = "midrange: INT8+NVFP4, low/high VRAM, 0.4-0.6 MP"
    else:
        profile = "native: high-VRAM profile, smoke-test before 0.98 MP"

    disk = shutil.disk_usage(RUNTIME)
    weights_dir = RUNTIME / "ComfyUI" / "models"
    weights = (sorted(str(p.relative_to(RUNTIME)) for p in
               weights_dir.glob("**/*.safetensors"))
               if weights_dir.exists() else [])
    result = {
        "root": str(ROOT),
        "runtime": str(RUNTIME),
        "gpu": gpu,
        "torch": torch,
        "ram_gb": memory_gb(),
        "python_runtime": python_runtime_info(),
        "disk_free_gb": round(disk.free / 1024**3, 1),
        "disk_warning": disk.free < 20 * 1024**3,
        "weights_present": weights,
        "forge": forge_info(),
        "vibevoice": vibevoice_info(),
        "vibevoice_environment": vibevoice_environment(),
        "external_tools": external_tool_info(),
        "recommended_profile": profile,
        "gpu_concurrency": 1,
    }
    print(json.dumps(result, indent=2))
    return 0 if torch.get("available") else 2


if __name__ == "__main__":
    raise SystemExit(main())
