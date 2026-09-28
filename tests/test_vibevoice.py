from __future__ import annotations

import os
import subprocess
import sys
import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from voice_runtime.client import (
    MIN_FREE_VRAM_MB, InvalidInput, Turn, VoiceError, build_conversation,
    home_dir, parse_script, parse_speaker_audio, require_free_vram,
)
from voice_runtime.run import prepare_model, run_tts, status_data
ROOT = Path(__file__).resolve().parents[1]


class ScriptParsingTests(unittest.TestCase):
    def test_plain_text_becomes_one_speaker_turn(self):
        turns = parse_script("Olá.\n\nEste é um teste.")
        self.assertEqual(turns, [Turn(speaker="0", text="Olá. Este é um teste.")])

    def test_labeled_script_preserves_turn_order_and_continuations(self):
        turns = parse_script(
            "Speaker 0: Olá!\nContinuação da fala.\n"
            "Speaker 1: Bom dia.\nSpeaker 0: Até logo."
        )
        self.assertEqual(
            turns,
            [
                Turn(speaker="0", text="Olá! Continuação da fala."),
                Turn(speaker="1", text="Bom dia."),
                Turn(speaker="0", text="Até logo."),
            ],
        )

    def test_script_rejects_empty_text(self):
        with self.assertRaisesRegex(InvalidInput, "empty"):
            parse_script(" \n\t")

    def test_speaker_ids_must_fit_model_roles(self):
        with self.assertRaisesRegex(InvalidInput, "0..3"):
            parse_script("Speaker 4: fora do limite")


class VoiceReferenceTests(unittest.TestCase):
    def test_reference_audio_is_attached_once_to_first_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            voice = Path(directory) / "voice.wav"
            voice.write_bytes(b"local reference")
            turns = parse_script("Speaker 0: Primeiro.\nSpeaker 0: Segundo.")

            conversation = build_conversation(turns, {"0": voice})

        self.assertEqual(len(conversation), 2)
        self.assertEqual(conversation[0]["role"], "0")
        self.assertEqual(conversation[0]["content"][0], {"type": "text", "text": "Primeiro."})
        self.assertEqual(
            conversation[0]["content"][1],
            {"type": "audio", "path": str(voice.resolve())},
        )
        self.assertEqual(conversation[1]["content"], [{"type": "text", "text": "Segundo."}])

    def test_reference_audio_arguments_require_existing_local_files(self):
        with tempfile.TemporaryDirectory() as directory:
            voice = Path(directory) / "voice.wav"
            voice.write_bytes(b"local reference")
            self.assertEqual(parse_speaker_audio([f"0={voice}"]), {"0": voice.resolve()})
            with self.assertRaisesRegex(InvalidInput, "does not exist"):
                parse_speaker_audio([f"0={voice}.missing"])
        with self.assertRaisesRegex(InvalidInput, "SPEAKER=PATH"):
            parse_speaker_audio(["Alice=voice.wav"])




class SafetyGateTests(unittest.TestCase):
    def test_model_download_requires_explicit_research_acknowledgment(self):
        with patch.dict(os.environ, {"VIBEVOICE_RESEARCH_OK": ""}):
            with self.assertRaisesRegex(VoiceError, "research and development"):
                prepare_model()

    def test_inference_requires_shared_gpu_lease(self):
        args = argparse.Namespace()
        with patch.dict(os.environ, {"VIBEVOICE_RESEARCH_OK": "1"}):
            with self.assertRaisesRegex(VoiceError, "shared GPU lease"):
                run_tts(args)

    def test_free_vram_guard_accepts_floor_and_refuses_below_it(self):
        require_free_vram(MIN_FREE_VRAM_MB * 1024**2)
        with self.assertRaisesRegex(VoiceError, "no inference was started"):
            require_free_vram(MIN_FREE_VRAM_MB * 1024**2 - 1)

class ReadinessTests(unittest.TestCase):
    def test_status_is_offline_and_reports_unprepared_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "voice"
            source = home / "source"
            python = home / "venv" / "bin" / "python"
            with patch.dict(os.environ, {
                "VIBEVOICE_HOME": str(home),
                "VIBEVOICE_SOURCE": str(source),
                "VIBEVOICE_PYTHON": str(python),
                "HF_HOME": str(home / "hf-cache"),
            }, clear=False):
                status = status_data()

        self.assertFalse(status["ready"])
        self.assertFalse(status["model_cached"])
        self.assertEqual(status["source"]["present"], False)
        self.assertEqual(status["dependencies"]["missing"], ["runtime venv"])

    def test_runtime_home_uses_xdg_and_honors_explicit_override(self):
        with tempfile.TemporaryDirectory() as directory:
            xdg_home = Path(directory) / "xdg"
            override = Path(directory) / "custom-runtime"
            with patch.dict(os.environ, {"XDG_DATA_HOME": str(xdg_home)}, clear=True):
                self.assertEqual(home_dir(), xdg_home / "postward" / "vibevoice")
            with patch.dict(os.environ, {
                "XDG_DATA_HOME": str(xdg_home),
                "VIBEVOICE_HOME": str(override),
            }, clear=True):
                self.assertEqual(home_dir(), override)

class CliTests(unittest.TestCase):
    def test_vibevoice_job_help_runs_as_a_standalone_script(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "vibevoice_job.py"), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)
if __name__ == "__main__":
    unittest.main()
