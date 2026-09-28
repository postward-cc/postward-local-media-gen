"""Small local adapter for the Transformers-native VibeVoice 1.5B model."""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MODEL_ID = "vibevoice/VibeVoice-1.5B-hf"
MODEL_REVISION = "d4cd82eb4371bf3e3d088e1ea7fa4eefb60449bf"
SOURCE_REVISION = "952326ddb264062466a888cf32a5b2f4e803e16e"
DEFAULT_DATA_SUBDIR = Path("postward") / "vibevoice"
MIN_FREE_VRAM_MB = 5632
AUTO_GPU_MEMORY_GIB = 5.5


class VoiceError(RuntimeError):
    """Safe, user-facing VibeVoice configuration or inference error."""


class InvalidInput(VoiceError):
    """A script or voice reference violates the local TTS contract."""


def require_free_vram(free_bytes: int) -> None:
    required_bytes = MIN_FREE_VRAM_MB * 1024**2
    if free_bytes < required_bytes:
        raise VoiceError(
            f"VibeVoice 1.5B requires at least {MIN_FREE_VRAM_MB} MiB free VRAM "
            "to keep its diffusion head on the GPU; no inference was started."
        )


@dataclass(frozen=True)
class Turn:
    speaker: str
    text: str


def home_dir() -> Path:
    configured = os.environ.get("VIBEVOICE_HOME")
    if configured:
        return Path(configured).expanduser()
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home).expanduser() if xdg_data_home else Path.home() / ".local" / "share"
    return base / DEFAULT_DATA_SUBDIR


def source_dir() -> Path:
    return Path(os.environ.get("VIBEVOICE_SOURCE", str(home_dir() / "source"))).expanduser()


def python_path() -> Path:
    return Path(
        os.environ.get("VIBEVOICE_PYTHON", str(home_dir() / "venv" / "bin" / "python"))
    ).expanduser()


def hf_home() -> Path:
    return Path(os.environ.get("HF_HOME", str(home_dir() / "hf-cache"))).expanduser()


def model_snapshot_path() -> Path:
    return (
        hf_home()
        / "hub"
        / "models--vibevoice--VibeVoice-1.5B-hf"
        / "snapshots"
        / MODEL_REVISION
    )


def parse_script(text: str) -> list[Turn]:
    """Parse plain text or Speaker 0..3 dialogue into ordered model turns."""
    if not text.strip():
        raise InvalidInput("input script is empty")

    speaker_header = re.compile(r"^\s*Speaker\s+(\d+)\s*:\s*(.*)$", re.IGNORECASE)
    turns: list[Turn] = []
    current_speaker = "0"
    current_lines: list[str] = []

    def flush() -> None:
        content = " ".join(line.strip() for line in current_lines if line.strip())
        if content:
            turns.append(Turn(current_speaker, content))

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = speaker_header.match(stripped)
        if match:
            flush()
            current_speaker = match.group(1)
            if current_speaker not in {"0", "1", "2", "3"}:
                raise InvalidInput("speaker IDs must be in the model role range 0..3")
            current_lines = [match.group(2)] if match.group(2).strip() else []
        else:
            current_lines.append(stripped)

    flush()
    if not turns:
        raise InvalidInput("input script contains no speech text")
    return turns


def parse_speaker_audio(values: list[str] | None) -> dict[str, Path]:
    """Parse local `speaker_id=path` voice references without reading them."""
    references: dict[str, Path] = {}
    for value in values or []:
        speaker, separator, raw_path = value.partition("=")
        if not separator or speaker not in {"0", "1", "2", "3"} or not raw_path:
            raise InvalidInput("voice references must use SPEAKER=PATH, with speaker IDs 0..3")
        if speaker in references:
            raise InvalidInput(f"more than one voice reference was supplied for speaker {speaker}")
        try:
            path = Path(raw_path).expanduser().resolve(strict=True)
        except OSError as exc:
            raise InvalidInput(f"voice reference does not exist: {raw_path}") from exc
        if not path.is_file():
            raise InvalidInput(f"voice reference is not a file: {raw_path}")
        references[speaker] = path
    return references


def build_conversation(
    turns: list[Turn], speaker_audio: dict[str, Path] | None = None
) -> list[dict[str, Any]]:
    """Build the Hugging Face chat template input, adding each voice once."""
    references = speaker_audio or {}
    used_speakers = {turn.speaker for turn in turns}
    unused = set(references) - used_speakers
    if unused:
        raise InvalidInput(f"voice reference has no matching script speaker: {', '.join(sorted(unused))}")

    voice_added: set[str] = set()
    conversation = []
    for turn in turns:
        content: list[dict[str, str]] = [{"type": "text", "text": turn.text}]
        if turn.speaker in references and turn.speaker not in voice_added:
            content.append({"type": "audio", "path": str(references[turn.speaker])})
            voice_added.add(turn.speaker)
        conversation.append({"role": turn.speaker, "content": content})
    return conversation


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generate_audio(
    *,
    model_path: str | Path,
    turns: list[Turn],
    speaker_audio: dict[str, Path],
    output_path: str | Path,
    seed: int,
    max_new_tokens: int,
) -> int:
    """Generate one WAV locally. Heavy imports stay inside the GPU code path."""
    try:
        import torch
        from transformers import AutoModelForTextToWaveform, AutoProcessor, set_seed
    except ImportError as exc:
        raise VoiceError(
            "VibeVoice dependencies are missing. Run scripts/bootstrap_vibevoice.sh."
        ) from exc

    free_bytes, _ = torch.cuda.mem_get_info()
    require_free_vram(free_bytes)

    set_seed(seed)
    dtype = torch.bfloat16
    model = AutoModelForTextToWaveform.from_pretrained(
        str(model_path),
        local_files_only=True,
        dtype=dtype,
        device_map="auto",
        max_memory={0: f"{AUTO_GPU_MEMORY_GIB:g}GiB", "cpu": "48GiB"},
    )
    processor = AutoProcessor.from_pretrained(str(model_path), local_files_only=True)
    model.eval()

    inputs = processor.apply_chat_template(
        build_conversation(turns, speaker_audio),
        return_dict=True,
        tokenize=True,
        add_generation_prompt=True,
    ).to(model.device, model.dtype)

    with torch.inference_mode():
        audio = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    saved = processor.save_audio(audio, output_path=str(destination))
    if not saved or not destination.is_file() or destination.stat().st_size <= 44:
        raise VoiceError("VibeVoice returned without writing a valid WAV output")
    return int(processor.feature_extractor.sampling_rate)
