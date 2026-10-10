# CPU sidecar containers

This repository runs its inference adapters as local processes: Forge behind
`FORGE_HOME`, ComfyUI/H3 under `comfyui-runtime/venv`, VibeVoice under
`voice_runtime/`. That topology is fixed by the shared GPU lock, the venv
layout and the documented `bootstrap.sh`. Containers are **not** part of it.

A container is appropriate for one narrow case: a CPU-only post-processing or
inspection step that the adapters do not implement, where the user already runs
Docker and prefers not to install the tool system-wide. Examples are thumbnail
generation, EXR conversion, a format check, or a batch resize after a frame
was already generated.

Do not containerize Forge, ComfyUI/H3, RTX VSR or speech. They need the NVIDIA
runtime, a persistent model cache and an exclusive lease on
`comfyui-runtime/state/gpu.lock`; giving them a second topology breaks the
concurrency contract in `reference/concurrency.md`.

## Hard rules

- **No GPU.** Do not pass `--gpus`. A sidecar that needs CUDA is inference and
  belongs in the local topology above.
- **No network.** Run with `--network none` unless a step genuinely needs to
  fetch something, and never to send user files off the machine. Installation
  and updates happen on the host, before the run.
- **CPU-only work may run concurrently** with a queued inference job, exactly
  like `ffmpeg` frame extraction already allowed in SKILL.md. It still consumes
  CPU, RAM and disk I/O; check `scripts/doctor.py` output before a large batch.
- **Read-only inputs.** Mount the source read-only; write only into the output
  directory. The container must never modify a generated asset in place.
- **No writes into the repository.** Outputs and manifests stay in the job's own
  directory, which is git-ignored.
- **Pin the image.** Use a specific tag or digest, never `latest`, and record it
  in the run notes. Image provenance matters as much as model provenance; see
  `reference/license-compliance.md` before using a tool whose license you have
  not reviewed.

## Mount layout

Use the job directory as the single writable mount and keep inputs on the host:

```bash
JOB_DIR="$PWD/forge_runtime/outputs/forge-inpaint-20261010-120000"
IMAGE="imagemagick@sha256:<digest>"
docker run --rm --network none --cpus 2 --memory 2g \
  --read-only --tmpfs /tmp \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$JOB_DIR,dst=/work" \
  "$IMAGE" \
  magick /work/01.png -resize 1024x1024 -strip /work/01_thumb.png
```

- `--user` keeps file ownership correct without a root-owned artifact.
- `--read-only` plus `--tmpfs /tmp` blocks the common image breakouts while
  still giving the tool scratch space.
- `--cpus` and `--memory` keep a batch from starving the inference host.
- Mount only the job directory. Never mount the repository root, `$HOME`,
  `$FORGE_HOME` or the model cache into a sidecar.

Writing into the job directory keeps the output contract intact: the container
produces one more file in a job folder that already carries its manifest.

## Selecting a tool

Pick by the narrowest capability that covers the step:

| Need | Upstream project | License | Entry point |
|---|---|---|---|
| Raster conversion, resize, montage | ImageMagick | ImageMagick-style | `magick` |
| Faster batch raster work | libvips | LGPL-2.1-or-later | `vips` |
| Smallest general raster tool | GraphicsMagick | GPL-2.0 | `gm` |
| Filters, inpainting-style filters | G'MIC | GPL-3.0 | `gmic` |
| EXR, ACES, OCIO pipelines | OpenImageIO | BSD-3-Clause | `oiiotool` |
| Scripted raster editing | GIMP | GPL-3.0 | `gimp-console` (needs Xvfb) |
| Vector to raster/PDF | Inkscape | GPL-3.0 | `inkscape` |
| PDF structure, encryption | qpdf | Apache-2.0 (recent releases) | `qpdf` |
| PDF rasterization | Ghostscript | GPL-3.0 | `gs` |
| Video decode, frame extraction, encode | FFmpeg | LGPL-2.1-or-later (GPL if built GPL) | `ffmpeg` |
| RAW development | darktable | GPL-3.0 | `darktable-cli` |
| Metadata read/write | ExifTool | Perl Artistic | `exiftool` |

Licenses above are from upstream projects and were not re-verified for a
specific image. Confirm the license of the exact image before use, the same
way model weights are gated.

Several of these ship as Docker Official Images under
`docker.io/library/<name>`; others are community-maintained or absent. Verify
before the first use rather than trusting a name written here:

```bash
docker manifest inspect docker.io/library/imagemagick:7.1.1-49  # exists?
docker buildx imagetools inspect <image>@sha256:<digest>       # record it
```

If no maintained image exists for a tool, prefer the distro package on the host
over building an unmaintained image, and record its version instead.

## Verifying what a sidecar produced

A container is not trusted output. After the run:

1. Confirm the exit status and that the expected file exists.
2. Compare the output SHA-256 against the value recorded in the job manifest;
   for a converted derivative, record the new digest in the run notes.
3. Open the result. A sidecar that reports success may still produce a
   flattened, color-shifted or metadata-stripped file.
4. Never let a sidecar rewrite `manifest.json`. It does not know the job
   contract.

## When not to use one

- The step already exists in an adapter. `scripts/compose_masked_edit.py` is
  CPU-only, dependency-light and honors the protected-pixel guarantee; prefer it
  over a container for masked composition.
- The tool is already on the host. The sidecar exists to avoid a system
  install, not to add capability.
- The step needs the GPU. That is inference; use the queue.
- Reproducibility matters more than isolation. A container that is not pinned
  and recorded is less reproducible than a host package with a known version.