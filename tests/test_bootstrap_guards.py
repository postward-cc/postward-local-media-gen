from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FETCH = ROOT / "comfyui-runtime" / "fetch_h3_weights.sh"
BOOTSTRAP = ROOT / "bootstrap.sh"
RELOCK = ROOT / "scripts" / "relock.sh"


def run_script(script: Path, *args: str, env: dict | None = None):
    environment = {**os.environ, **(env or {})}
    return subprocess.run(["bash", str(script), *args], capture_output=True,
                          text=True, env=environment, timeout=120)


class H3LicenseGateTests(unittest.TestCase):
    """The weights gate is the repository's one hard licensing promise."""

    def test_download_is_refused_without_the_acknowledgement(self):
        result = run_script(FETCH, env={"LICENSE_OK": "0"})

        self.assertEqual(result.returncode, 2)
        self.assertIn("LICENSE_OK", result.stderr)

    def test_refusal_creates_no_download_state(self):
        with tempfile.TemporaryDirectory() as directory:
            workdir = Path(directory) / "comfyui-runtime"
            workdir.mkdir()
            fetch = workdir / "fetch_h3_weights.sh"
            fetch.write_text(FETCH.read_text(), encoding="utf-8")

            result = run_script(fetch, env={"LICENSE_OK": "", "HF_HOME": directory})

            self.assertEqual(result.returncode, 2)
            self.assertFalse((workdir / "downloads").exists())
            self.assertFalse((workdir / "ComfyUI" / "models").exists())

    def test_acknowledgement_clears_the_gate(self):
        """With the gate set the script must stop refusing; where it goes next
        is this machine's business, the license check is not.

        HF_HUB_OFFLINE keeps the rest harmless: on a workstation whose runtime
        venv does work, the script would otherwise start a 41 GB download from a
        test.
        """
        with tempfile.TemporaryDirectory() as directory:
            result = run_script(FETCH, env={"LICENSE_OK": "1",
                                            "HF_HOME": directory,
                                            "HF_HUB_OFFLINE": "1"})

        self.assertNotIn("explicit confirmation of applicable license",
                         result.stderr)


class BootstrapGuardTests(unittest.TestCase):
    def test_unknown_comfyui_version_refuses_instead_of_resolving_another_release(self):
        result = run_script(BOOTSTRAP, "--dry-run",
                            env={"COMFYUI_VERSION": "v0.99.0-not-real"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requirements-comfyui-v0.99.0-not-real.txt", result.stderr)
        self.assertIn("--refresh-comfyui", result.stderr)

    def test_dry_run_never_installs_anything(self):
        result = run_script(BOOTSTRAP, "--dry-run")

        self.assertEqual(result.returncode, 0)
        self.assertIn("no files or packages were changed", result.stdout)


class RelockGuardTests(unittest.TestCase):
    def test_unknown_target_is_rejected(self):
        result = run_script(RELOCK, "not-a-target")

        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown argument", result.stderr)

    def test_missing_uv_is_reported_with_the_install_command(self):
        result = run_script(RELOCK, env={"UV_BIN": "uv-does-not-exist"})

        self.assertEqual(result.returncode, 2)
        self.assertIn("astral.sh/uv", result.stderr)


if __name__ == "__main__":
    unittest.main()