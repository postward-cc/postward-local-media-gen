# Removing or replacing a tool

Deletion is a cutover, not an addition. The old path goes away in the same
commit that adds the new one.

## Grep first, then decide

```bash
grep -rn '<tool-or-module>' --include='*.py' --include='*.md' --include='*.json' --include='*.sh' . \
  | grep -v '^./ComfyUI' | grep -v 'venv/'
```

Every hit is either something to delete or something to repoint. There is no
third category.

## Delete, do not deprecate

Remove in one pass:

- the implementation file
- every call site
- the probe declaration in `scripts/doctor.py`, if any
- the row in `SKILL.md` → **Tooling alternatives** and **Tool preference order**
- the entry in `skill.json`
- the reference table row in `reference/docker-sidecars.md`
- every test that asserted the old behaviour
- the name from `README.md`, `INSTALL.md` and the repository layout tree

**What not to leave behind:** a shim that forwards to the new path, a
`# deprecated` alias, a "kept for backwards compatibility" re-export, or a
parameter that silently does nothing. Two ways to do one thing means two ways
to be wrong, and an agent cannot tell which one is correct.

## If it owned data

Removing a tool is easy; removing its artifacts is not. Decide explicitly
whether existing outputs, caches and state files are deleted, kept, or migrated,
and write down which. Do not leave a directory that nothing reads and nothing
removes.

For state under `comfyui-runtime/state/` and the various `outputs/` trees,
those paths are git-ignored, so nothing in this repository can remove them on a
workstation. Say that in the migration notes instead of implying it happens
automatically.

## If it had a lock entry

Regenerate. A lock that keeps a removed package is worse than no lock:

```bash
./scripts/relock.sh
python scripts/doctor.py verify-locks
```

## Replace, don't dual-publish

When B replaces A, do it in one commit: delete A, add B, move every caller,
move the tests. A commit that adds B while leaving A working is a branch, and
branches are how two conventions get established.

Only exception: a genuinely reversible, explicitly discussed migration — and
then the old path carries a comment saying when it goes, not a polite note
saying it is deprecated.

## Verify

```bash
./scripts/check.sh
grep -rn '<removed-name>' . | grep -v '^./ComfyUI'   # expect nothing
```

Read the diff in full. Removal mistakes are invisible to tests and obvious in a
review.