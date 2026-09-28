# Postward Local Media Generation

Use this skill when a user asks OMP to generate or transform images, video or
speech locally on the workstation. This skill covers Forge image editing,
VibeVoice text-to-speech, MiniMax H3 video generation, multi-shot continuity,
and NVIDIA RTX Video Super Resolution.

## Installation contract

When a user asks to install/configure this toolkit, start with a read-only
inventory:

```bash
python scripts/doctor.py
python forge_runtime/run.py status
python voice_runtime/run.py status
```

Then configure the requested local adapter using its documented environment
variables. `FORGE_HOME` points to an already-installed Forge; this repository
does not install Forge automatically. ComfyUI/H3 setup is optional and uses
`./bootstrap.sh`; VibeVoice setup is optional and uses
`./scripts/bootstrap_vibevoice.sh`. Review model terms before downloading
weights. Never commit workstation-specific paths, private inputs, generated
assets or runtime manifests to this repository.

The main bootstrap is idempotent and installs under
`comfyui-runtime/venv` and `comfyui-runtime/ComfyUI`. It does not download H3
weights. Read `INSTALL.md` for choices and `skill.json` for the machine-readable
contract.


## First-time local configuration

For a new workstation or an agent handed this repository:

1. Run `python scripts/doctor.py` and the two adapter status commands above.
   Use their results; do not assume a particular GPU, checkout path, model
   directory, installed service, or disk layout.
2. For Forge, discover or ask for an existing local Forge installation, then
   set `FORGE_HOME`, `FORGE_PYTHON`, and `FORGE_CHECKPOINT_PATH` as needed.
   Re-run `python forge_runtime/run.py status`. Forge setup details:
   `reference/image-generation.md`.
3. For video, ask before installing ComfyUI dependencies with `./bootstrap.sh`.
   H3 weights are a separate license-gated download; never set `LICENSE_OK=1`
   without explicit confirmation that the applicable license covers the user.
4. For optional speech, ask before running
   `./scripts/bootstrap_vibevoice.sh`. Its default data location follows
   `XDG_DATA_HOME`; `VIBEVOICE_HOME` overrides it. Model weights are a separate
   5.42 GB download gated by `VIBEVOICE_RESEARCH_OK=1`.
5. Before any generation, check the measured free VRAM, acquire the shared
   queue, and get approval when the user has not already requested that
   inference. Never free VRAM by killing another process.

Keep machine settings in the user's shell/session or their own untracked
configuration. Never write machine-specific paths into this repository.
## Operating contract

1. Run `python scripts/doctor.py` for the workstation summary,
   `python forge_runtime/run.py status` for Forge, and
   `python voice_runtime/run.py status` for VibeVoice.
2. Read `reference/hardware-profiles.md` and use detected capabilities.
3. Review model terms before downloads. VibeVoice 1.5B requires the explicit
   `VIBEVOICE_RESEARCH_OK=1` acknowledgment and is research-only.
4. Acquire the shared GPU job lock before inference.
5. Run only one GPU inference job at a time across Forge, ComfyUI/H3 and
   VibeVoice.
6. Use a unique output directory for every request.
7. Record source-image and mask SHA-256 for image edits/inpaints, plus each
   I2V source hash.
8. Return the job ID, output paths, resolution, model, settings and warnings.

## Capabilities

- Text → video: run `comfyui-runtime/run_workflow.py` with
  `comfyui-runtime/workflows/video_minimax_h3_t2v.json`, serialized through
  `scripts/job_queue.py run`. Review the license and install H3 weights first.

  ```bash
  python scripts/job_queue.py run --kind h3-t2v -- \
    python comfyui-runtime/run_workflow.py \
      comfyui-runtime/workflows/video_minimax_h3_t2v.json \
      --megapixels 0.2 --duration 1 --turbo-steps 8 --seed 431 \
      --prompt "A small paper owl flies through a moonlit forest." \
      --out-dir comfyui-runtime/outputs/first-video
  ```
- Image → video: use the H3 I2V workflow with a verified first frame; see
  `comfyui-runtime/RUNBOOK.md` for input preparation and VRAM limits.
- Multi-shot narrative: `comfyui-runtime/run_hogwarts_shots.py`; replace its
  sample shot data before use and preserve each shot's source-frame hash.
- RTX VSR: `comfyui-runtime/submit_rtx_vsr.py`.
- Local image generation/editing/inpaint: `forge_runtime/run.py` supports txt2img,
  img2img and masked inpaint. Set `FORGE_HOME`; use `scripts/forge_job.py` so
  the operation holds the shared GPU lock. Inpainting masks use white for
  editable pixels and black for protected pixels.
- Local speech generation: `voice_runtime/run.py` uses pinned VibeVoice 1.5B HF;
  `scripts/vibevoice_job.py` holds the shared GPU lock. Bootstrap its isolated
  runtime with `scripts/bootstrap_vibevoice.sh`; choose storage with
  `VIBEVOICE_HOME` or XDG data-home configuration. Download weights only with
  `VIBEVOICE_RESEARCH_OK=1 python voice_runtime/run.py prepare`. Portuguese is
  unsupported by the selected model and may only be tested experimentally.
- For TTS, use the shared GPU queue:

  ```bash
  VIBEVOICE_RESEARCH_OK=1 python scripts/vibevoice_job.py tts -- \
    --text "Hello, this is a local speech test." --seed 431
  ```
- Forge is an existing local install configured through `FORGE_HOME`;
  `bootstrap.sh` does not install or update it. See `forge_runtime/RUNBOOK.md`
  for Forge commands; `voice_runtime/RUNBOOK.md` for speech setup, supported
  languages, outputs and recovery; and `reference/image-generation.md` for
  image configuration and the adapter contract.

## Hardware decision tree

| Detected state | Action |
|---|---|
| No CUDA GPU | Do not start H3; explain that this skill requires an NVIDIA GPU. |
| < 8 GB VRAM | Do not download the official 8 GB profile. Recommend a separately licensed INT4 profile or stop. |
| 8–10 GB VRAM | INT8 + NVFP4, `--lowvram`, 0.2–0.4 MP, one job only. |
| 12–16 GB VRAM | INT8 + NVFP4, low/high VRAM depending on doctor output, 0.4–0.6 MP. |
| 16 GB+ VRAM | Consider high-VRAM/native 0.98 MP after a smoke test. |

Never infer a profile from the GPU model name alone; use measured free VRAM,
RAM, disk, driver and PyTorch CUDA availability.

## Concurrent requests

The supported execution path serializes inference through one GPU lock:

```text
request A ─┐
request B ─┼── job_queue.py run + flock ── one inference at a time
request C ─┘
```

CPU-only work such as ffmpeg frame extraction, metadata inspection, and output
copying may run concurrently if disk/RAM limits allow. Do not launch concurrent
ComfyUI or Forge inference.

`job_queue.py run` executes a command synchronously while holding the GPU lease:

```bash
python scripts/job_queue.py run --kind h3-t2v -- \
  python comfyui-runtime/run_workflow.py ...
python scripts/forge_job.py inpaint -- --image owl.webp --mask ears.png --prompt "..."
```

`job_queue.py enqueue` only records a queued metadata item; this repository does
not currently have a background dispatcher for those records. Do not report
enqueued jobs as running/queued inference work unless an external worker is
actually consuming them.

## License gate

H3 weights are not downloaded implicitly. The user must explicitly confirm the
applicable MiniMax license. The downloader requires:

```bash
LICENSE_OK=1 ./comfyui-runtime/fetch_h3_weights.sh
```

The skill must never set `LICENSE_OK=1` based on inference or silently bypass
the gate. See `reference/license-compliance.md`.

## Failure policy

- OOM: mark the job failed, preserve the log, lower resolution/duration or use
  a more aggressive offload profile; do not retry the same request unchanged.
- Process crash: mark orphaned `running` jobs as `interrupted` on the next
  doctor/queue invocation and release the lock.
- Missing model: report the exact missing filename and the license-gated
  download command.
- Wrong source frame: fail before submission if the declared source path or
  SHA-256 does not match the job manifest.
- Concurrent Forge/H3 use: wait for the other engine or ask the user before
  stopping a known service; never kill unrelated GPU processes.

## Output contract

Every completed generation returns a JSON manifest. A local image job includes:

```json
{
  "job_id": "forge-inpaint-...",
  "status": "success",
  "operation": "inpaint",
  "local_inference": true,
  "model": "sd_xl_base_1.0.safetensors",
  "resolution": "1200x900",
  "source": {"path": "<user-provided source asset>", "sha256": "..."},
  "mask": {"path": "<user-provided mask>", "sha256": "..."},
  "outputs": [{"path": "<generated image asset>", "sha256": "..."}],
  "warnings": []
}
```

Video jobs also return duration/audio metadata. State the final output path;
never ask the user to search through Forge or ComfyUI history manually.
