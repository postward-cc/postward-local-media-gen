#!/usr/bin/env python3
"""Verify that the repository's declared contracts match its actual contents.

`doctor.py` measures the workstation. This checks the repository itself: the
manifest, the documentation and the probes that describe them. Those three are
separate files maintained by hand, and nothing but a person reading all three
catches them drifting apart — which is exactly the failure that makes a change
feel unsafe: a tool is probed but not declared, or the docs point at a file
that was renamed.

Run it directly or through ./scripts/check.sh.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "doctor", ROOT / "scripts" / "doctor.py")
doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doctor)

MARKDOWN_SUFFIX = ".md"
LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)#]+?)\)")
PATH_PATTERN = re.compile(r"`([\w][\w./-]*\.(?:py|sh|md|json|txt|lock))`")


def tracked_files(suffix: str) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", f"*{suffix}"], cwd=ROOT, capture_output=True,
        text=True, check=True)
    return [ROOT / line for line in result.stdout.splitlines() if line]


def markdown_files(root: Path) -> list[Path]:
    """Documents to inspect: the tracked ones for this repository, or everything
    under ``root`` when a caller passes a different tree."""
    if root == ROOT:
        return tracked_files(MARKDOWN_SUFFIX)
    skip = {"venv", "node_modules", ".git", "ComfyUI", "__pycache__"}
    return sorted(p for p in root.rglob("*.md")
                  if not any(part in skip for part in p.parts))


def markdown_problems(root: Path = ROOT) -> dict[str, list[str]]:
    """Broken links and referenced files that do not exist, per document."""
    report: dict[str, list[str]] = {}
    for path in markdown_files(root):
        text = path.read_text()
        problems = []
        for target in LINK_PATTERN.findall(text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if not (path.parent / target).exists():
                problems.append(f"broken link: {target}")
        for referenced in PATH_PATTERN.findall(text):
            if "/" not in referenced or referenced.startswith(("./", "../")):
                continue
            if not (root / referenced).exists():
                problems.append(f"referenced file does not exist: {referenced}")
        if problems:
            report[str(path.relative_to(root))] = sorted(set(problems))
    return report


def manifest_problems(root: Path = ROOT) -> list[str]:
    """skill.json must agree with what doctor actually probes."""
    manifest = json.loads((root / "skill.json").read_text())
    declared = set(manifest["external_tools"]["ids"])
    probed = {entry[0] for entry in doctor.EXTERNAL_TOOLS}
    problems = []
    for tool in sorted(declared - probed):
        problems.append(f"{tool} is declared in skill.json but never probed")
    for tool in sorted(probed - declared):
        problems.append(f"{tool} is probed by doctor.py but not declared in skill.json")
    for playbooks in manifest.get("playbooks", {}).get("entries", []):
        if not (root / playbooks).exists():
            problems.append(f"{playbooks} is declared in skill.json but missing")
    index = manifest.get("playbooks", {}).get("index")
    if index and not (root / index).exists():
        problems.append(f"{index} is declared in skill.json but missing")
    return problems


def report(root: Path = ROOT) -> dict:
    docs = markdown_problems(root)
    manifest = manifest_problems(root)
    ok = not docs and not manifest
    return {
        "documents_checked": len(markdown_files(root)),
        "markdown_problems": docs,
        "manifest_problems": manifest,
        "status": "ok" if ok else "problems",
    }


def main() -> int:
    result = report()
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())