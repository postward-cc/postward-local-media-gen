from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("doctor", ROOT / "scripts" / "doctor.py")
doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doctor)


class ExternalToolProbeTests(unittest.TestCase):
    def test_missing_tool_is_reported_unavailable_not_raised(self):
        tools = (("nothing", "raster", "No Such Tool", "--version", ("definitely-not-installed-xyz",)),)

        report = doctor.external_tool_info(tools)

        entry = report["nothing"]
        self.assertFalse(entry["available"])
        self.assertIsNone(entry["path"])
        self.assertIsNone(entry["version"])

    def test_installed_tool_records_resolved_path_and_version(self):
        tools = (("fake", "raster", "Fake Tool", "--version", ("fake-tool",)),)

        with patch.object(doctor.shutil, "which", return_value="/usr/bin/fake-tool"), \
             patch.object(doctor, "command", return_value="Fake Tool 2.1\nsecond line") as run:
            report = doctor.external_tool_info(tools)

        self.assertTrue(report["fake"]["available"])
        self.assertEqual(report["fake"]["path"], "/usr/bin/fake-tool")
        self.assertEqual(report["fake"]["version"], "Fake Tool 2.1")
        self.assertEqual(report["fake"]["capability"], "raster")
        run.assert_called_once_with("/usr/bin/fake-tool", "--version", timeout=10)

    def test_second_candidate_resolves_when_first_is_absent(self):
        tools = (("raster", "raster", "ImageMagick", "--version", ("magick", "convert")),)

        with patch.object(doctor.shutil, "which", side_effect=lambda c: "/usr/bin/convert" if c == "convert" else None), \
             patch.object(doctor, "command", return_value="Version: ImageMagick 7.1.1-49"):
            report = doctor.external_tool_info(tools)

        self.assertEqual(report["raster"]["path"], "/usr/bin/convert")
        self.assertTrue(report["raster"]["available"])

    def test_present_binary_that_fails_to_report_version_stays_unavailable_data(self):
        tools = (("quiet", "pdf", "Quiet", "--version", ("quiet-tool",)),)

        with patch.object(doctor.shutil, "which", return_value="/usr/bin/quiet-tool"), \
             patch.object(doctor, "command", return_value=None):
            report = doctor.external_tool_info(tools)

        entry = report["quiet"]
        self.assertTrue(entry["available"])
        self.assertIsNone(entry["version"])

    def test_every_shipped_tool_declares_a_probe_capability(self):
        for key, capability, name, version_flag, candidates in doctor.EXTERNAL_TOOLS:
            with self.subTest(tool=key):
                self.assertTrue(key and capability and name and version_flag)
                self.assertTrue(candidates)
                self.assertTrue(all(c.islower() for c in candidates))


class CommandTimeoutTests(unittest.TestCase):
    def test_timeout_is_reported_as_missing_output_not_an_exception(self):
        import subprocess

        with patch.object(doctor.subprocess, "check_output",
                          side_effect=subprocess.TimeoutExpired(cmd="x", timeout=1)):
            self.assertIsNone(doctor.command("true"))


class PythonRuntimeTests(unittest.TestCase):
    def test_broken_venv_is_reported_without_raising(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "venv" / "bin" / "python"

            info = doctor.python_runtime_info(missing)

        self.assertFalse(info["venv_python_exists"])
        self.assertFalse(info["venv_python_usable"])
        self.assertIsNone(info["venv_python_version"])

    def test_dangling_symlink_counts_as_not_usable(self):
        with tempfile.TemporaryDirectory() as directory:
            venv = Path(directory) / "venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin" / "python").symlink_to(Path(directory) / "gone" / "python3")

            info = doctor.python_runtime_info(venv)

        self.assertFalse(info["venv_python_exists"])
        self.assertFalse(info["venv_python_usable"])

    def test_usable_venv_reports_its_interpreter_version(self):
        with tempfile.TemporaryDirectory() as directory:
            venv = Path(directory) / "venv"
            bin_dir = venv / "bin"
            bin_dir.mkdir(parents=True)
            python = bin_dir / "python"
            python.write_text("#!/bin/sh\necho 'Python 3.12.15'\n")
            python.chmod(0o755)

            info = doctor.python_runtime_info(venv)

        self.assertTrue(info["venv_python_usable"])
        self.assertEqual(info["venv_python_version"], "Python 3.12.15")

    def test_running_interpreter_is_checked_against_the_supported_range(self):
        info = doctor.python_runtime_info(Path("/nonexistent"))

        expected = f"{sys.version_info.major}.{sys.version_info.minor}"
        self.assertEqual(info["doctor_python"], expected)
        self.assertEqual(
            info["doctor_python_in_range"],
            (3, 11) <= sys.version_info[:2] < (3, 14),
        )
        self.assertEqual(info["pinned_version"], doctor.PINNED_PYTHON_VERSION)


class CudaTagCheckTests(unittest.TestCase):
    def test_lock_without_cuda_build_is_rejected(self):
        lock = "torch==2.14.1 \\\n    --hash=sha256:aa\ntorchvision==0.29.1\ntorchaudio==2.11.0\n"

        problems = doctor.cuda_tag_problems(lock)

        self.assertEqual(len(problems), 3)
        self.assertTrue(all("+cu128" in problem for problem in problems))

    def test_lock_with_cuda_build_passes(self):
        lock = ("torch==2.11.0+cu128 \\\n    --hash=sha256:aa\n"
                "torchvision==0.26.0+cu128 \\\n    --hash=sha256:bb\n"
                "torchaudio==2.11.0+cu128 \\\n    --hash=sha256:cc\n")

        self.assertEqual(doctor.cuda_tag_problems(lock), [])

    def test_expected_tag_is_configurable(self):
        lock = "torch==2.11.0+cu126\n"

        self.assertEqual(doctor.cuda_tag_problems(lock, "cu126"), [])
        self.assertTrue(doctor.cuda_tag_problems(lock, "cu128"))

    def test_only_the_torch_family_is_checked(self):
        lock = "triton==3.6.0\nnumpy==2.5.3\nnvidia-vfx==0.2.0.0\n"

        self.assertEqual(doctor.cuda_tag_problems(lock), [])

    def test_check_lock_command_reports_problems_and_fails(self):
        import json
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "bad.lock"
            lock.write_text("torch==2.14.1\n")
            completed = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "doctor.py"), "check-lock", str(lock)],
                capture_output=True, text=True,
            )

        self.assertEqual(completed.returncode, 1)
        self.assertTrue(json.loads(completed.stdout)["problems"])


if __name__ == "__main__":
    unittest.main()