from __future__ import annotations

import importlib.util
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


if __name__ == "__main__":
    unittest.main()