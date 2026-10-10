from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from forge_runtime.masked_composition import CompositionError, composite_masked_edit


class MaskedCompositionTests(unittest.TestCase):
    def test_white_mask_edits_only_selected_pixels_and_records_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base_path = root / "base.png"
            edit_path = root / "edit.png"
            mask_path = root / "mask.png"
            output_path = root / "step.png"

            Image.new("RGB", (8, 6), (240, 20, 10)).save(base_path)
            Image.new("RGB", (8, 6), (10, 30, 240)).save(edit_path)
            mask = Image.new("L", (8, 6), 0)
            ImageDraw.Draw(mask).rectangle((2, 2, 4, 3), fill=255)
            mask.save(mask_path)

            manifest = composite_masked_edit(base_path, edit_path, mask_path, output_path)

            with Image.open(output_path) as image:
                self.assertEqual(image.format, "PNG")
                result = image.convert("RGB")
            self.assertEqual(result.getpixel((0, 0)), (240, 20, 10))
            self.assertEqual(result.getpixel((3, 2)), (10, 30, 240))
            self.assertTrue(manifest["protected_pixels_exact"])
            self.assertEqual(manifest["base"]["sha256"], hashlib.sha256(base_path.read_bytes()).hexdigest())
            self.assertEqual(manifest["output"]["sha256"], hashlib.sha256(output_path.read_bytes()).hexdigest())
            self.assertTrue(Path(str(output_path.with_suffix(".manifest.json"))).is_file())

    def test_feather_blends_edges_but_keeps_black_mask_pixels_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base_path = root / "base.png"
            edit_path = root / "edit.png"
            mask_path = root / "mask.png"
            output_path = root / "step.png"

            Image.new("RGB", (9, 9), (0, 0, 0)).save(base_path)
            Image.new("RGB", (9, 9), (255, 255, 255)).save(edit_path)
            mask = Image.new("L", (9, 9), 0)
            ImageDraw.Draw(mask).rectangle((3, 3, 5, 5), fill=255)
            mask.save(mask_path)

            manifest = composite_masked_edit(
                base_path, edit_path, mask_path, output_path, feather_radius=1.0
            )

            with Image.open(output_path) as image:
                result = image.convert("RGB")
            self.assertEqual(result.getpixel((0, 0)), (0, 0, 0))
            edge = result.getpixel((2, 4))[0]
            self.assertGreater(edge, 0)
            self.assertLess(edge, 255)
            self.assertTrue(manifest["protected_pixels_exact"])

    def test_protected_alpha_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base_path = root / "base.png"
            edit_path = root / "edit.png"
            mask_path = root / "mask.png"
            output_path = root / "step.png"

            base = Image.new("RGBA", (3, 2), (240, 20, 10, 255))
            base.putpixel((0, 0), (12, 34, 56, 0))
            base.save(base_path)
            Image.new("RGBA", (3, 2), (10, 30, 240, 255)).save(edit_path)
            mask = Image.new("L", (3, 2), 0)
            mask.putpixel((2, 1), 255)
            mask.save(mask_path)

            composite_masked_edit(base_path, edit_path, mask_path, output_path)

            with Image.open(output_path) as image:
                result = image.convert("RGBA")
            self.assertEqual(result.getpixel((0, 0)), (12, 34, 56, 0))
            self.assertEqual(result.getpixel((2, 1)), (10, 30, 240, 255))

    def test_dimension_mismatch_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new("RGB", (8, 6), "red").save(root / "base.png")
            Image.new("RGB", (7, 6), "blue").save(root / "edit.png")
            Image.new("L", (8, 6), 255).save(root / "mask.png")

            with self.assertRaisesRegex(CompositionError, "dimensions must match"):
                composite_masked_edit(root / "base.png", root / "edit.png", root / "mask.png", root / "step.png")
            self.assertFalse((root / "step.png").exists())

    def test_lossless_output_is_required_and_inputs_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base_path = root / "base.png"
            edit_path = root / "edit.png"
            mask_path = root / "mask.png"
            Image.new("RGB", (2, 2), "red").save(base_path)
            Image.new("RGB", (2, 2), "blue").save(edit_path)
            Image.new("L", (2, 2), 255).save(mask_path)

            with self.assertRaisesRegex(CompositionError, "must be PNG"):
                composite_masked_edit(base_path, edit_path, mask_path, root / "step.webp")
            with self.assertRaisesRegex(CompositionError, "must not overwrite an input"):
                composite_masked_edit(base_path, edit_path, mask_path, base_path)

    def test_existing_output_requires_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base_path = root / "base.png"
            edit_path = root / "edit.png"
            mask_path = root / "mask.png"
            output_path = root / "step.png"
            Image.new("RGB", (2, 2), "red").save(base_path)
            Image.new("RGB", (2, 2), "blue").save(edit_path)
            Image.new("L", (2, 2), 255).save(mask_path)
            output_path.write_bytes(b"existing output")

            with self.assertRaisesRegex(CompositionError, "already exists"):
                composite_masked_edit(base_path, edit_path, mask_path, output_path)


if __name__ == "__main__":
    unittest.main()
