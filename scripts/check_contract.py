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

LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)#]+?)\)")
PATH_PATTERN = re.compile(r"`([\w][\w./-]*\.(?:py|sh|md|json|txt|lock))`")


def git_ignored(root: Path, candidates: list[str]) -> set[str]:
    """Which candidates git ignores: runtime state and generated outputs.

    Documentation legitimately cites paths that only exist after a bootstrap,
    such as the GPU lease file. Requiring those to exist would fail every fresh
    checkout, including CI, while catching nothing.
    """
    if not candidates:
        return set()
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"], cwd=root, input="\n".join(candidates),
        capture_output=True, text=True)
    if result.returncode not in (0, 1):
        return set()
    return set(line for line in result.stdout.splitlines() if line)


def markdown_files(root: Path) -> list[Path]:
    """Every document under ``root``, including ones not yet committed.

    Enumerating tracked files only would silently skip a new document until it
    was committed, which is exactly when the mistake is easiest to make. The
    check therefore walks the working tree and skips the directories that hold
    checkouts and generated output.
    """
    skip = {"venv", "node_modules", ".git", "ComfyUI", "__pycache__",
            "outputs", "state", ".check-venv", ".local-check-venv"}
    return sorted(p for p in root.rglob("*.md")
                  if not any(part in skip for part in p.parts))


def markdown_problems(root: Path = ROOT) -> dict[str, list[str]]:
    """Broken links and referenced files that do not exist, per document."""
    report: dict[str, list[str]] = {}
    documents = markdown_files(root)
    referenced_paths = sorted({
        found
        for path in documents
        for found in PATH_PATTERN.findall(path.read_text())
        if "/" in found and not found.startswith(("./", "../"))
    })
    ignored = git_ignored(root, referenced_paths)

    for path in documents:
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
            if referenced in ignored:
                continue
            if not (root / referenced).exists():
                problems.append(f"referenced file does not exist: {referenced}")
        if problems:
            report[str(path.relative_to(root))] = sorted(set(problems))
    return report


def frontmatter(text: str) -> dict[str, str]:
    """Parse the leading YAML frontmatter without a YAML dependency.

    Supports scalar values and ``|`` / ``>`` block scalars, plus one level of
    nesting — which is all this check needs. The repository runs on the
    standard library, and a parser that silently mis-read a block scalar would
    be worse than none: it would report a field as present while the harness
    reads something else.
    """
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 3)
    if end == -1:
        return {}
    lines = text[4:end].splitlines()
    fields: dict[str, str] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1].isspace():          # handled while reading its parent
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value in ("|", ">", "|-", ">-"):
            block = []
            while index < len(lines) and (not lines[index].strip()
                                          or lines[index][:1].isspace()):
                block.append(lines[index].strip())
                index += 1
            fields[key] = "\n".join(part for part in block if part)
            continue
        fields[key] = value
        for nested in lines[index:]:
            if not nested[:1].isspace():
                break
            if not nested.strip():
                continue
            child, _, child_value = nested.strip().partition(":")
            fields[f"{key}.{child}"] = child_value.strip()
    return fields


def skill_package_problems(root: Path = ROOT) -> list[str]:
    """The packaged skill must carry what a harness reads, and one version.

    The version lives in ``metadata.version`` inside SKILL.md, not as a
    top-level field, and it must agree with ``skill.json``. Both facts were
    learned the hard way: a top-level ``version`` is rejected by the registry,
    and ``omp skill version patch`` starts from what it finds in the frontmatter.
    """
    fields = frontmatter((root / "SKILL.md").read_text())
    problems = []
    if not fields:
        return ["SKILL.md has no YAML frontmatter; harnesses cannot match this skill"]
    for required in ("name", "description", "metadata.version"):
        if not fields.get(required):
            problems.append(f"SKILL.md frontmatter is missing {required}")
    manifest_version = json.loads((root / "skill.json").read_text()).get("version")
    packaged = fields.get("metadata.version")
    if packaged and manifest_version and packaged != manifest_version:
        problems.append(
            f"SKILL.md metadata.version is {packaged} but skill.json says "
            f"{manifest_version}; they must be one version"
        )
    return problems


def manifest_problems(root: Path = ROOT) -> list[str]:
    """skill.json must agree with what doctor actually probes."""
    manifest = json.loads((root / "skill.json").read_text())
    declared = set(manifest["external_tools"].get("ids", []))
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


PLUGIN_MANIFESTS: tuple[tuple[str, str], ...] = (
    (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"),
    (".codex-plugin/plugin.json", ".agents/plugins/marketplace.json"),
)


def plugin_manifest_problems(root: Path = ROOT) -> list[str]:
    """Every plugin manifest must agree with the repository it describes.

    They are what lets a harness discover this skill from the repository alone,
    so a version or name that drifts from ``SKILL.md`` makes the discovery
    wrong rather than merely untidy. Two families are declared because two
    harnesses read two layouts; both are checked against the same ``SKILL.md``
    so neither can drift independently.
    """
    problems = []
    skill_name = frontmatter((root / "SKILL.md").read_text()).get("name")
    skill_version = frontmatter((root / "SKILL.md").read_text()).get("metadata.version")

    for plugin_rel, market_rel in PLUGIN_MANIFESTS:
        plugin_path, market_path = root / plugin_rel, root / market_rel
        label = plugin_rel.split("/")[0]
        if not plugin_path.exists():
            problems.append(f"{plugin_rel} is missing")
            continue
        if not market_path.exists():
            problems.append(f"{market_rel} is missing")
            continue

        plugin = json.loads(plugin_path.read_text())
        market = json.loads(market_path.read_text())

        if plugin.get("name") != skill_name:
            problems.append(
                f"{label}: plugin name {plugin.get('name')!r} does not match "
                f"SKILL.md {skill_name!r}")
        version = plugin.get("version")
        if version != skill_version:
            problems.append(
                f"{label}: version {version!r} does not match SKILL.md "
                f"metadata.version {skill_version!r}")
        if not plugin.get("license"):
            problems.append(f"{label}: plugin.json is missing license")
        if not plugin.get("repository"):
            problems.append(f"{label}: plugin.json is missing repository")
        if label == ".claude-plugin" and "." not in plugin.get("skills", []):
            problems.append(f"{label}: plugin.json must include the root SKILL.md")
        if label == ".codex-plugin" and plugin.get("skills") != "./":
            problems.append(f"{label}: plugin.json must point at the root skill")
        entries = market.get("plugins") or []
        entry = next((e for e in entries if e.get("name") == plugin.get("name")), None)
        if not entry:
            problems.append(
                f"{label}: {market_rel} does not list a plugin named "
                f"{plugin.get('name')!r}")
        elif label == ".codex-plugin":
            source = entry.get("source", {})
            if source != {"source": "local", "path": "./"}:
                problems.append(
                    f"{label}: marketplace source must be local path './', "
                    f"got {source!r}")
        if market.get("name") != "postward":
            problems.append(
                f"{label}: marketplace name {market.get('name')!r} must be "
                f"'postward' so both harnesses register the same catalog")
    return problems


def report(root: Path = ROOT) -> dict:
    docs = markdown_problems(root)
    manifest = manifest_problems(root)
    package = skill_package_problems(root)
    plugin = plugin_manifest_problems(root)
    ok = not docs and not manifest and not package and not plugin
    return {
        "documents_checked": len(markdown_files(root)),
        "markdown_problems": docs,
        "manifest_problems": manifest,
        "package_problems": package,
        "plugin_manifest_problems": plugin,
        "status": "ok" if ok else "problems",
    }


def main() -> int:
    result = report()
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())