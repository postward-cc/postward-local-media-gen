# Evaluating a third-party CLI

Someone proposes an external tool: replace an adapter, add a capability, or sit
beside what exists. Evaluate it before adopting it. The PhotoCraft evaluation
that produced `SKILL.md` → **Tooling alternatives** is the worked example.

## Establish the facts before forming an opinion

| Question | How |
|---|---|
| Licence | The repository's `LICENSE` files, not the homepage. Note third-party assets: fonts, icons, translations |
| Where it runs | Prebuilt binaries per platform, or source build only |
| Headless or UI | Look for a CLI entry point and what it can do without a window |
| Automatable | CLI, JSON control channel, MCP server |
| Activity | Recent commits, open issues, release cadence, whether it is alpha |
| GPU | Whether it needs CUDA at all, and whether the headless path uses the GPU or a CPU reference path |

Read the source. `Dockerfile` presence is not evidence of an image that does
what you need — a web/WASM build served by a web server is a UI in a browser.

## Run the honest experiment

An evaluation that ends in adoption without a measurement is a preference
disguised as a finding.

1. Build or install it on this machine.
2. Run **the same task an existing adapter already does**, on a real input.
3. Compare outputs on the axis the user cares about: pixels preserved, latency,
   reproducibility, provenance that survives the operation.
4. Record what you observed, including failure modes.

If the build takes hours or the comparison cannot be made honestly, say that in
the recommendation rather than adopting on enthusiasm.

## Match it against the preference order

`SKILL.md` → **Tool preference order** decides the outcome:

1. A repository adapter outranks everything.
2. An installed external tool outranks a container.
3. A pinned sidecar is last.
4. A hosted service is never.

Adopting an external tool over a working adapter is a decision that must be
justified by measurement, because it changes the output contract: the manifest
then describes a process this repository does not control.

## Container question

Before proposing a container, check whether an image exists. Upstream projects
frequently ship desktop binaries and a WASM build but no container image — in
which case someone on your side must build and publish it, which makes your
project the redistributor and carries the licence obligations: preserve
`NOTICE`, ship `LICENSE` files, and include third-party asset licences.

That obligation is real and outlives the pull request.

## Decide and record

Write the outcome into the repository, not into a chat:

- adopted as a fallback → `SKILL.md` **Tooling alternatives** and, if needed,
  `reference/` documentation with the install and pin steps
- adopted as a replacement → this is a cutover; see
  [`removing-a-tool.md`](removing-a-tool.md)
- rejected → one line in the commit or an ADR saying what was measured and why
  it lost. A rejected tool with a recorded reason is not re-litigated in six
  months; a rejection with no record is.

## Do not

- Do not add it to `skill.json` → `local_adapters`. That list means "this
  repository ships and supports this".
- Do not claim a behaviour you did not run. Mark it `[INFERENCE]` and say what
  would confirm it.
- Do not add it to CI unless it can run there: no GPU, no model weights, fast.
  Local confidence belongs in `tests/local/` via `./scripts/check_local.sh`.