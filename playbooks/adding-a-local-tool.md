# Adding a local tool

A capability this repository does not implement, where an existing local
headless tool can do the job. Example: a request for EXR conversion, which no
adapter covers.

**If the repository should own the operation, use
[`adding-an-adapter.md`](adding-an-adapter.md) instead.** The dividing line is
the manifest and the queue: if the output needs a job id, SHA-256 provenance
and GPU lock arbitration, it is an adapter, not a tool.

## Decide it belongs here

1. Read `SKILL.md` → **Tool preference order**. A fallback is for work the
   adapters do not perform, never a replacement for a working adapter.
2. Read `SKILL.md` → **Tooling alternatives**. If the capability is already
   listed, you are not adding a tool; you are choosing between existing ones.
3. Confirm no adapter covers it. Grep `forge_runtime/`, `voice_runtime/`,
   `comfyui-runtime/` and `scripts/`.

## Add the probe

An agent must be able to tell whether the tool exists. Every tool the skill may
invoke is declared in `scripts/doctor.py`:

```python
EXTERNAL_TOOLS: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    # key, capability, display name, version flag, candidate executables
    ("exiftool", "metadata", "ExifTool", "-ver", ("exiftool",)),
)
```

Rules the probe depends on:

- The version flag is the one that makes that tool print a version, verified by
  running it. `convert --version` and `qpdf --version` differ.
- List every common executable name, most preferred first (`magick`, then
  `convert`), because distributions disagree about which one ships.
- A missing tool is data, never an exception. Probes must never raise.
- Keep the version probe bounded by a timeout; `command()` takes one.

Verify it before moving on:

```bash
python scripts/doctor.py | python -c "import json,sys;print(json.load(sys.stdin)['external_tools'])"
python scripts/check_contract.py   # probe and manifest must agree
```

Run `check_contract.py` last: it fails if you added the probe without adding
the id to `skill.json`, or the reverse.

## Wire it into the skill

| File | Change |
|---|---|
| `SKILL.md` | One row in the **Tooling alternatives** table |
| `skill.json` | The tool id in `external_tools.ids` |
| `reference/docker-sidecars.md` | Upstream project, licence, entry point — only if a container may run it |
| `README.md` | The "Other local tools" sentence, if the tool is worth naming |

Do **not** add it to `local_adapters`. That list means "this repository ships
and supports this", and the repository does not build this tool.

## Test the probe, not the tool

```python
def test_missing_tool_is_reported_unavailable_not_raised(self):
    ...
```

Copy the shape from `tests/test_doctor.py`. Assert the probe's behaviour:
resolution, candidate fallback, version capture, timeout. Assert nothing about
the third-party tool's own output — that is not yours to test and it will
change under you.

## Verify

```bash
./scripts/check.sh
```

Then confirm on a machine that does have the tool that `doctor.py` reports it
with a version, and on one that does not that it reports `available: false`
without failing. If only one machine is available, say so in the commit; do not
claim the other direction was observed.