# Optional local tools

Capabilities this skill does not implement, mapped to local tools that do, in
preference order.

**This repository installs none of these, vendors none of them, pins none of
them and maintains none of them.** An entry here is a pointer: what the tool is
good for, where it comes from, and under what licence. If one breaks or
disappears, this file goes stale and that is acceptable — the entries exist to
save you from not knowing a good tool exists, not to support it.

Use this file together with `SKILL.md` → **Tooling alternatives**, which covers
the common categories with tools already installed on most workstations. This
file covers what that table does not: application-scale suites with their own
command line.

Two rules when picking from here:

1. **Prefer the command line.** Every tool below ships a CLI headless, without
   a window. A suite whose only interface is a window is not usable here.
2. **Prefer what is already installed.** A tool the user already has beats a
   better tool nobody has. Ask before installing anything.

## Image editing, layers, PSD

| Tool | Good at | Licence |
|---|---|---|
| [PhotoCraft](https://getartcraft.com/apps/photocraft) | Layered image editing with real PSD files, adjustment layers, masks, layer styles, type. Ships `photocraft-cli` with `convert`, `info`, `run`, `batch`, `commands`, `mcp`, `serve` | MIT OR Apache-2.0 |

The CLI is the reason this is listed rather than the app. Its `batch --actions`
runs a saved action list over a folder without a window, which is what a
pipeline wants. Building it from source needs a Rust toolchain; the prebuilt
CLI binaries for the Crafting apps are macOS-only, with `pdfcraft` the sole
exception shipping a Linux tarball. See
[`third-party-evaluation.md`](third-party-evaluation.md) for what was verified,
when, and what remains inference.

## Vector illustration

| Tool | Good at | Licence |
|---|---|---|
| [VectorCraft](https://getartcraft.com/apps/vectorcraft) | Vector illustration, SVG-oriented, with a `vectorcraft-cli` | Apache-2.0 |
| [Inkscape](https://inkscape.org) | SVG authoring and batch export to raster or PDF; already listed in the SKILL.md table | GPL-3.0 |

## Video editing

| Tool | Good at | Licence |
|---|---|---|
| [FilmCraft](https://getartcraft.com/apps/filmcraft) | Multi-track timeline editing with a `filmcraft-cli` | Apache-2.0 |

This skill generates video. It does not cut it. `ffmpeg` from the SKILL.md table
covers frame extraction, transcoding and assembly, which is usually the
threshold where a pipeline actually stops needing a timeline.

## RAW photo development

| Tool | Good at | Licence |
|---|---|---|
| [LightCraft](https://getartcraft.com/apps/lightcraft) | Photo library and raw developer with a `lightcraft-cli` | Apache-2.0 |
| [darktable](https://www.darktable.org), [RawTherapee](https://rawtherapee.org) | Mature raw development, both with command line interfaces; already listed in the SKILL.md table | GPL-3.0 |

## PDF assembly

| Tool | Good at | Licence |
|---|---|---|
| [PdfCraft](https://getartcraft.com/apps/pdfcraft) | Read, combine, split and secure PDFs, with a `pdfcraft-cli`; the only Crafting app shipping prebuilt Linux binaries | Apache-2.0 |
| [qpdf](https://qpdf.readthedocs.io), Ghostscript, mutool | Already in the SKILL.md table, and usually sufficient | Apache-2.0, GPL-3.0, MIT |

## Motion graphics and compositing

| Tool | Good at | Licence |
|---|---|---|
| [EffectCraft](https://getartcraft.com/apps/effectcraft) | Motion graphics and visual effects with an `effectcraft-cli` | Apache-2.0 |

## Page layout and publishing

| Tool | Good at | Licence |
|---|---|---|
| [DesignCraft](https://getartcraft.com/apps/designcraft) | Multi-column page layout with threaded text and a `designcraft-cli` | Apache-2.0 |

## If none of these fit

Follow the resolution order in `SKILL.md` → **When this table does not cover the
need**: check the adapters, then what the user's machine already has, declare
any tool the user names before relying on it, and only then consider a pinned
sidecar. A hosted service is never an option, and an unasked install is never
an option.

The order in this file is a preference, not a ranking of quality. If the user
already has one of these installed, that is the one to use.