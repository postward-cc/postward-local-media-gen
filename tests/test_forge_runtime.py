from __future__ import annotations

import argparse

import base64
import io
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
import importlib.util
from unittest.mock import patch

from PIL import Image

from forge_runtime.client import (
    DEFAULT_MIN_FREE_VRAM_MB,
    ForgeClient,
    ForgeError,
    ImageInput,
    InsufficientVRAM,
    InvalidInput,
    build_img2img_payload,
    build_inpaint_payload,
    build_txt2img_payload,
    loopback_base_url,
    load_image,
    prepare_image_pair,
)

ROOT = Path(__file__).resolve().parents[1]


def image_input(name: str, width: int = 1024, height: int = 1024, data: str = "QUJD") -> ImageInput:
    return ImageInput(
        path=Path(name),
        data_uri=f"data:image/png;base64,{data}",
        width=width,
        height=height,
        sha256="a" * 64,
        mime_type="image/png",
    )


class ImageInputTests(unittest.TestCase):
    def test_load_image_records_hash_of_original_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.png"
            Image.new("RGB", (64, 64), (100, 80, 60)).save(path)
            raw = path.read_bytes()

            image = load_image(path)

        self.assertEqual((image.width, image.height), (64, 64))
        self.assertEqual(image.sha256, hashlib.sha256(raw).hexdigest())


class PayloadTests(unittest.TestCase):
    def test_txt2img_is_one_image_and_has_explicit_seed(self):
        payload = build_txt2img_payload(prompt="paper owl", seed=71)
        self.assertEqual(payload["seed"], 71)
        self.assertEqual(payload["batch_size"], 1)
        self.assertEqual(payload["n_iter"], 1)
        self.assertEqual((payload["width"], payload["height"]), (1024, 1024))

    def test_img2img_references_source_and_uses_low_default_denoise(self):
        source = image_input("source.png")
        payload = build_img2img_payload(image=source, prompt="paint ears")
        self.assertEqual(payload["init_images"], [source.data_uri])
        self.assertEqual(payload["denoising_strength"], 0.55)

    def test_inpaint_white_mask_edits_only_white_region(self):
        source = image_input("source.png")
        mask = image_input("mask.png", data="TUFT")
        payload = build_inpaint_payload(image=source, mask=mask, prompt="paint the ears")
        self.assertEqual(payload["init_images"], [source.data_uri])
        self.assertEqual(payload["mask"], mask.data_uri)
        self.assertEqual(payload["inpainting_mask_invert"], 0)
        self.assertEqual(payload["inpainting_fill"], 1)
        self.assertEqual(payload["denoising_strength"], 0.45)
        self.assertFalse(payload["inpaint_full_res"])

    def test_black_mask_can_be_declared_as_edit_region_explicitly(self):
        payload = build_inpaint_payload(
            image=image_input("source.png"), mask=image_input("mask.png"),
            prompt="paint the background", inpainting_mask_invert=1,
        )
        self.assertEqual(payload["inpainting_mask_invert"], 1)

    def test_mask_dimension_mismatch_is_rejected_before_http(self):
        with self.assertRaisesRegex(InvalidInput, "do not match"):
            prepare_image_pair(image_input("source.png", 1024, 1024), image_input("mask.png", 512, 512))

    def test_invalid_resolution_and_denoise_are_rejected(self):
        with self.assertRaises(InvalidInput):
            build_txt2img_payload(prompt="owl", width=2048, height=2048)
        with self.assertRaises(InvalidInput):
            build_img2img_payload(image=image_input("x"), prompt="owl", denoising_strength=1.1)

    def test_remote_forge_url_is_refused(self):
        with self.assertRaisesRegex(InvalidInput, "refuses remote"):
            loopback_base_url("http://example.com:7860")
        self.assertEqual(loopback_base_url("http://127.0.0.1:7860"), "http://127.0.0.1:7860")


class ForgeClientTests(unittest.TestCase):
    def test_urllib_transport_decodes_json_response(self):
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b'{"ok": true}')):
            result = ForgeClient._urllib_transport(
                "GET", "http://127.0.0.1:7860/sdapi/v1/options", None, 2
            )
        self.assertEqual(result, {"ok": True})

    def test_vram_guard_prevents_posting_generation(self):
        calls = []
        def transport(method, url, payload, timeout):
            calls.append((method, url))
            if url.endswith("/sdapi/v1/options"):
                return {"sd_model_checkpoint": "sd_xl_base_1.0.safetensors"}
            if url.endswith("/sdapi/v1/sd-models"):
                return [{"model_name": "sd_xl_base_1.0.safetensors"}]
            if url.endswith("/sdapi/v1/memory"):
                return {"cuda": {"system": {"free": 900 * 1024**2, "total": 8 * 1024**3}}}
            raise AssertionError("generation request must not be sent")
        client = ForgeClient(transport=transport)
        payload = build_txt2img_payload(prompt="owl")
        with self.assertRaises(InsufficientVRAM):
            client.generate("txt2img", payload, minimum_vram_mb=DEFAULT_MIN_FREE_VRAM_MB)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all("/sdapi/v1/" in url for _, url in calls))

    def test_generation_decodes_api_result_without_a_gpu(self):
        def transport(method, url, payload, timeout):
            if method == "GET" and url.endswith("/sdapi/v1/options"):
                return {"sd_model_checkpoint": "sd_xl_base_1.0.safetensors [abc]"}
            if method == "GET" and url.endswith("/sdapi/v1/sd-models"):
                return [{"model_name": "sd_xl_base_1.0.safetensors"}]
            if method == "GET" and url.endswith("/sdapi/v1/memory"):
                return {"cuda": {"system": {"free": 7 * 1024**3, "total": 8 * 1024**3}}}
            if method == "POST" and url.endswith("/sdapi/v1/txt2img"):
                return {
                    "images": [base64.b64encode(b"png-data").decode()],
                    "info": "{\"all_seeds\":[9]}",
                    "parameters": {"prompt": "owl", "seed": 9},
                }
            raise AssertionError((method, url))
        client = ForgeClient(transport=transport)
        generation = client.generate("txt2img", build_txt2img_payload(prompt="owl"))
        self.assertEqual(generation.images, [b"png-data"])
        self.assertEqual(generation.provider_info, "{\"all_seeds\":[9]}")
        self.assertEqual(generation.provider_parameters["seed"], 9)

    def test_status_reports_checkpoint_models_and_vram(self):
        def transport(method, url, payload, timeout):
            if url.endswith("/sdapi/v1/options"):
                return {"sd_model_checkpoint": "sd_xl_base_1.0.safetensors [abc]"}
            if url.endswith("/sdapi/v1/sd-models"):
                return [{"model_name": "sd_xl_base_1.0.safetensors"}]
            if url.endswith("/sdapi/v1/memory"):
                return {"cuda": {"system": {"free": 6 * 1024**3, "total": 8 * 1024**3}}}
            raise AssertionError(url)
        status = ForgeClient(transport=transport).status()
        self.assertEqual(status["model"], "sd_xl_base_1.0.safetensors [abc]")
        self.assertIn("sd_xl_base_1.0.safetensors", status["models"])
        self.assertGreater(status["cuda_free_mb"], 5000)


class QueueIntegrationTests(unittest.TestCase):
    def test_forge_jobs_are_wrapped_by_existing_gpu_queue(self):
        import importlib.util
        path = ROOT / "scripts" / "forge_job.py"
        spec = importlib.util.spec_from_file_location("forge_job", path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        command = module.build_queue_command("inpaint", ["--image", "owl.png", "--mask", "ears.png"], "/forge/venv/bin/python")
        self.assertEqual(command[1:5], [str(ROOT / "scripts" / "job_queue.py"), "run", "--kind", "forge-inpaint"])
        self.assertIn("--", command)
        self.assertIn("--mask", command)
        self.assertEqual(command[-1], "ears.png")

    def test_job_queue_passes_shared_job_id_and_lock_marker_to_child(self):
        import importlib.util
        path = ROOT / "scripts" / "job_queue.py"
        spec = importlib.util.spec_from_file_location("job_queue", path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            module.STATE = base
            module.JOBS = base / "jobs.json"
            module.LOCK = base / "gpu.lock"
            captured = {}
            class Proc:
                returncode = 0
            def fake_run(command, env=None):
                captured["command"] = command
                captured["env"] = env
                return Proc()
            args = argparse.Namespace(kind="forge-inpaint", command=["python", "run.py", "inpaint"])
            with patch.object(module.subprocess, "run", side_effect=fake_run):
                self.assertEqual(module.run(args), 0)
            self.assertEqual(captured["env"]["POSTWARD_GPU_LOCK_HELD"], "1")
            self.assertTrue(captured["env"]["POSTWARD_JOB_ID"].startswith("forge-inpaint-"))



class DoctorTests(unittest.TestCase):
    @staticmethod
    def load_doctor():
        path = ROOT / "scripts" / "doctor.py"
        spec = importlib.util.spec_from_file_location("postward_doctor", path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module

    def test_doctor_command_handles_missing_local_binary(self):
        self.assertIsNone(self.load_doctor().command("postward-missing-binary-92347"))

    def test_doctor_reports_unconfigured_forge_without_machine_defaults(self):
        from forge_runtime.client import ForgeUnavailable

        class Offline:
            def __init__(self, _url):
                pass
            def status(self):
                raise ForgeUnavailable("connection refused")

        with patch.dict(os.environ, {}, clear=True):
            result = self.load_doctor().forge_info(Offline)
        self.assertFalse(result["installation"]["configured"])
        self.assertIsNone(result["installation"]["home"])

    def test_doctor_reports_unavailable_forge_without_generation(self):
        from forge_runtime.client import ForgeUnavailable

        class Offline:
            def __init__(self, _url):
                pass
            def status(self):
                raise ForgeUnavailable("connection refused")

        result = self.load_doctor().forge_info(Offline)
        self.assertFalse(result["available"])
        self.assertFalse(result["can_generate"])
        self.assertIn("connection refused", result["error"])

    def test_doctor_requires_expected_model_and_free_vram(self):
        class Ready:
            def __init__(self, _url):
                pass
            def status(self):
                return {
                    "base_url": "http://127.0.0.1:7860",
                    "model": "sd_xl_base_1.0.safetensors [abc]",
                    "models": ["sd_xl_base_1.0.safetensors"],
                    "cuda_free_mb": 5000,
                    "memory": {},
                }

        result = self.load_doctor().forge_info(Ready)
        self.assertTrue(result["available"])
        self.assertTrue(result["model_loaded"])
        self.assertTrue(result["can_generate"])

        class LowVRAM(Ready):
            def status(self):
                value = super().status()
                value["cuda_free_mb"] = 512
                return value
        self.assertFalse(self.load_doctor().forge_info(LowVRAM)["can_generate"])
class ForgeInterpreterTests(unittest.TestCase):
    def test_forge_python_prefers_explicit_environment_configuration(self):
        path = Path("configured-forge-python")
        with patch.dict(os.environ, {"FORGE_PYTHON": str(path)}, clear=True):
            module_spec = importlib.util.spec_from_file_location(
                "postward_forge_job", ROOT / "scripts" / "forge_job.py"
            )
            module = importlib.util.module_from_spec(module_spec)
            assert module_spec and module_spec.loader
            module_spec.loader.exec_module(module)
            self.assertEqual(module.forge_python(), path)


class CliSafetyTests(unittest.TestCase):
    def test_direct_generation_refuses_to_run_outside_gpu_queue(self):
        import contextlib
        import io
        from forge_runtime import run

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("POSTWARD_GPU_LOCK_HELD", None)
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                code = run.main(["txt2img", "--prompt", "owl"])
        self.assertEqual(code, 2)
        self.assertIn("shared GPU lease", error.getvalue())

    def test_status_is_allowed_without_gpu_lock(self):
        import contextlib
        import io
        from forge_runtime import run

        class FakeClient:
            def __init__(self, _url):
                pass
            def status(self):
                return {"available": True, "cuda_free_mb": 7000}

        output = io.StringIO()
        with patch.object(run, "ForgeClient", FakeClient), contextlib.redirect_stdout(output):
            code = run.main(["status"])
        self.assertEqual(code, 0)
        self.assertIn('"available": true', output.getvalue())


class ManifestTests(unittest.TestCase):
    def test_manifest_records_provenance_without_inline_image_data(self):
        from forge_runtime.run import save_result
        source = image_input("source-image.png")
        mask = image_input("edit-mask.png")
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"POSTWARD_JOB_ID": "forge-test-1"}):
            result = save_result(
                [b"fake-png"], operation="inpaint",
                payload={"prompt": "brown ears", "init_images": ["SECRETBASE64"], "mask": "SECRETMASK"},
                status={"base_url": "http://127.0.0.1:7860", "model": "sdxl"},
                out_root=temp, source=source, mask=mask,
            )
            manifest = json.loads((Path(temp) / "forge-test-1" / "manifest.json").read_text())
            self.assertEqual(result["job_id"], "forge-test-1")
            self.assertEqual(manifest["source"]["sha256"], source.sha256)
            self.assertEqual(manifest["mask"]["sha256"], mask.sha256)
            self.assertEqual(manifest["settings"], {"prompt": "brown ears"})
            self.assertNotIn("SECRET", json.dumps(manifest))
if __name__ == "__main__":
    unittest.main()
