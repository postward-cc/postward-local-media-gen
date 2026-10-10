from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_contract", ROOT / "scripts" / "check_contract.py")
check_contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_contract)


class MarkdownProblemTests(unittest.TestCase):
    def _root(self, files: dict[str, str]) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        return root

    def test_broken_relative_link_is_reported(self):
        root = self._root({"README.md": "see [gone](nope/file.md)\n"})

        problems = check_contract.markdown_problems(root)

        self.assertIn("README.md", problems)
        self.assertTrue(any("nope/file.md" in p for p in problems["README.md"]))

    def test_absolute_external_links_are_not_inspected(self):
        root = self._root({"README.md": "[web](https://example.com/x)\n"
                                         "[mail](mailto:a@b.c)\n"})

        self.assertEqual(check_contract.markdown_problems(root), {})

    def test_resolvable_link_passes(self):
        root = self._root({"README.md": "see [ok](target.md)\n", "target.md": "hi\n"})

        self.assertEqual(check_contract.markdown_problems(root), {})

    def test_referenced_repository_file_that_was_renamed_is_reported(self):
        root = self._root({"README.md": "run `scripts/renamed.py` first\n"})

        problems = check_contract.markdown_problems(root)

        self.assertTrue(any("scripts/renamed.py" in p
                            for p in problems["README.md"]))

    def test_bare_filename_without_a_directory_is_not_treated_as_a_path(self):
        root = self._root({"README.md": "see `README.md` and `python3`\n"})

        self.assertEqual(check_contract.markdown_problems(root), {})

    def test_document_not_yet_committed_is_still_inspected(self):
        """Enumerating tracked files only would skip a brand new document."""
        root = self._root({"README.md": "see [gone](nope/file.md)\n"})

        self.assertIn("README.md", check_contract.markdown_problems(root))


class ManifestProblemTests(unittest.TestCase):
    def _root(self, manifest: dict) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "skill.json").write_text(json.dumps(manifest))
        return root

    def test_tool_declared_but_never_probed_is_reported(self):
        root = self._root({"external_tools": {"ids": ["ffmpeg", "imaginary-tool"]}})

        problems = check_contract.manifest_problems(root)

        self.assertTrue(any("imaginary-tool" in p for p in problems))

    def test_probed_tool_missing_from_the_manifest_is_reported(self):
        probed = sorted(entry[0] for entry in check_contract.doctor.EXTERNAL_TOOLS)
        root = self._root({"external_tools": {"ids": probed[:1]}})

        problems = check_contract.manifest_problems(root)

        self.assertTrue(any(f"{probed[1]} is probed" in p for p in problems),
                        problems[:3])

    def test_agreement_is_silence(self):
        ids = sorted(entry[0] for entry in check_contract.doctor.EXTERNAL_TOOLS)
        root = self._root({"external_tools": {"ids": ids}})

        self.assertEqual(check_contract.manifest_problems(root), [])

    def test_declared_playbook_file_must_exist(self):
        ids = sorted(entry[0] for entry in check_contract.doctor.EXTERNAL_TOOLS)
        root = self._root({"external_tools": {"ids": ids},
                           "playbooks": {"index": "playbooks/README.md",
                                         "entries": ["playbooks/ghost.md"]}})

        problems = check_contract.manifest_problems(root)

        self.assertTrue(any("playbooks/ghost.md" in p for p in problems))

    def test_missing_playbook_index_is_reported(self):
        ids = sorted(entry[0] for entry in check_contract.doctor.EXTERNAL_TOOLS)
        root = self._root({"external_tools": {"ids": ids},
                           "playbooks": {"index": "playbooks/absent.md",
                                         "entries": []}})

        self.assertTrue(any("absent.md" in p for p in check_contract.manifest_problems(root)))


class RepositoryContractTests(unittest.TestCase):
    def test_this_repository_is_consistent(self):
        result = check_contract.report()

        self.assertEqual(result["status"], "ok",
                         json.dumps({"markdown": result["markdown_problems"],
                                     "manifest": result["manifest_problems"]},
                                    indent=2))
        self.assertGreaterEqual(result["documents_checked"], 20)


if __name__ == "__main__":
    unittest.main()