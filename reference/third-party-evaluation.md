# Third-party evaluation: ArtCraft Crafting Apps

- Status: **evaluated, pending upstream** — no answer yet on two questions
  asked in the ArtCraft Discord on 2026-10-10.
- Repository: [github.com/storytold](https://github.com/storytold)
- Suite: [getartcraft.com/apps](https://getartcraft.com/apps)
- Relevant app here: **PhotoCraft**, a clean-room image editor in Rust that
  carries the load for the questions below.

Nothing from this suite is installed, declared or invoked by this repository.
This file records what was measured so the evaluation is not rebuilt from
scratch, and so a future change does not re-litigate it without new evidence.

## What was measured

| Fact | Source |
|---|---|
| Dual licensed MIT OR Apache-2.0; clean-room, no proprietary code or assets | `LICENSE-MIT`, `LICENSE-APACHE`, `NOTICE`, `ATTRIBUTION.md` |
| Third-party assets carry their own licences: fonts (OFL), icons, dictionaries, UI translations | the repository `Dockerfile`, which copies those licence files into the image |
| Prebuilt `*-cli` assets are macOS-universal only. `pdfcraft` is the sole exception with Linux x86_64 and aarch64 tarballs | release assets for photocraft v0.6.0, filmcraft v0.5.0, vectorcraft v0.8.0, lightcraft v0.5.0, effectcraft v0.7.0, designcraft v0.5.0 |
| The desktop app is available for Linux as AppImage, `.deb`, `.rpm`, tarball and Flatpak — but the CLI binary is not in those packages | v0.6.0 release assets |
| The repository `Dockerfile` builds the WASM web bundle behind nginx. It is a community-maintained self-hosting recipe for the browser build, not a CLI image | `Dockerfile`, header comment |
| `photocraft-cli` exposes `convert`, `info`, `run`, `batch`, `commands`, `mcp` and `serve` over one registry of 500+ commands shared with the UI | README → Built for agents; `docs/development.md` |
| `photocraft-cli mcp` already exists, built on the Rust MCP SDK, headless or bridged to a running app | `docs/mcp.md` |
| Filesystem authority fails closed: without `--automation-read-root` / `--automation-write-root` there is none. The environment-variable equivalents do **not** apply to headless `mcp` or `serve` | `docs/mcp.md`, `docs/control-protocol.md` |
| The MCP surface is not a subset of the control protocol; `control_call {method, params}` is the escape hatch that reaches the remainder | `docs/control-protocol.md`, MCP bridge mapping table |
| Export and the test suite use the CPU compositor; wgpu is the canvas of the interactive UI | `docs/development.md` |
| Building from source needs Rust 1.95 or newer over a 24-crate workspace | `Cargo.toml`, `Dockerfile` |

## Not measured

Two claims remain **[INFERENCE]** and were not confirmed by running anything:

1. Whether headless `photocraft-cli` opens a wgpu device. The evidence says the
   export path is CPU, and `PHOTOCRAFT_CPU_CANVAS=1` exists, but nothing here
   proves the CLI does not touch the GPU. If it does, it contends with the GPU
   lease and must take it.
2. Whether the CLI crate builds for `x86_64-unknown-linux-musl`. The web build
   already links musl, but the CLI pulls in the GPU crates.

Both resolve only by building the CLI on this machine.

## Two questions asked upstream

1. Are container images for the headless CLIs planned, or deliberately out of
   scope?
2. Since `photocraft-cli mcp` exists, is there interest in making it easier to
   adopt — documented configuration for Claude Code, Codex or opencode, or a
   published wrapper package? None was found in the repository.

A third, optional question asked whether PhotoCraft may be listed as an
optional fallback in this skill's documentation, with an explicit statement
that nothing here requires approval, that no binary would be forked, vendored
or redistributed, and that the listing could be removed on request.

## Where this would land, if it lands

Not in `skill.json` → `local_adapters`. That list means this repository ships
and supports the thing, and it does not build PhotoCraft.

- Rank 2 of `SKILL.md` → **Tool preference order**: an external local tool
  above a container, below a repository adapter.
- A row in `SKILL.md` → **Tooling alternatives**, plus a probe entry in
  `scripts/doctor.py` and the tool id in `skill.json` →
  `external_tools.ids`. `scripts/check_contract.py` fails the build if the two
  disagree.
- Nothing changes while no adapter covers the step it would serve.

## Why not a container

There is no official image. Publishing one would make this repository the
redistributor, carrying the obligation to preserve `NOTICE` and to ship the
licence files for the third-party fonts, icons, dictionaries and translations.
A container would only help a machine without a Rust toolchain, and
`pdfcraft` already ships a Linux tarball for that case.

## Why not the MCP, specifically

For the operations this repository performs — compose a masked edit, export a
file — `photocraft-cli batch --actions <file>` is stateless and sufficient. The
MCP is worth it for interactive agent-driven editing against a live document,
which is not this repository's shape. Registering their server would also be a
different layer from this repository: a skill that invokes scripts, versus a
long-lived stateful server. It would be documentation, not a wrapper.