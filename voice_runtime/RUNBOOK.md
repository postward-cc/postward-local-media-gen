# VibeVoice local speech generation

This adapter runs the pinned `vibevoice/VibeVoice-1.5B-hf` checkpoint through
Transformers' native `AutoModelForTextToWaveform` support. The repository's
ComfyUI/H3 environment is not modified. The optional VibeVoice checkout, voice
samples, Python environment and model cache live in a separate user-owned data
directory.

The checkout is pinned to
[`vibevoice-community/VibeVoice` revision `952326d`](https://github.com/vibevoice-community/VibeVoice/tree/952326ddb264062466a888cf32a5b2f4e803e16e).
Only its `demo/voices` samples are sparse-checked out. The HF-native model is
pinned to revision
[`d4cd82e`](https://huggingface.co/vibevoice/VibeVoice-1.5B-hf/tree/d4cd82eb4371bf3e3d088e1ea7fa4eefb60449bf).
The community repository's own `pyproject.toml` pins Transformers 4.51.3; that
package is deliberately not installed because the HF model requires Transformers 5.17.0.
The checkout supplies the included demo voice samples and source provenance;
verify consent before using any identifiable speaker sample.

## 1. Setup and readiness

```bash
./scripts/bootstrap_vibevoice.sh
VIBEVOICE_RESEARCH_OK=1 python voice_runtime/run.py prepare
python voice_runtime/run.py status
```

Bootstrap installs a separate Torch 2.11/cu128 runtime, Transformers 5.17.0,
Diffusers, Accelerate, SoundFile and Librosa. It clones pinned source voice
samples but does **not** download model weights. By default, `VIBEVOICE_HOME`
is `${XDG_DATA_HOME:-$HOME/.local/share}/postward/vibevoice`; set
`VIBEVOICE_HOME` to any user-owned data directory with sufficient space.
`prepare` requires the research-use acknowledgment and downloads the pinned
5.42 GB model. `status` is read-only and never loads weights or submits
inference.

## 2. Single-speaker TTS

```bash
VIBEVOICE_RESEARCH_OK=1 python scripts/vibevoice_job.py tts -- \
  --text "Olá. Este é um teste experimental em português." \
  --seed 431 --max-new-tokens 256
```

A UTF-8 script file may replace `--text`. The input can be plain single-speaker
text or ordered dialogue with headers:

```text
Speaker 0: Olá, eu sou a primeira pessoa.
Speaker 1: E eu sou a segunda.
Speaker 0: Vamos começar.
```

The supported model role IDs are `0` through `3`. Add one local consented voice
reference per role with repeatable `--speaker-audio ID=PATH` options. A reference
is read locally and attached only to that speaker's first turn. No source text or
voice audio is uploaded by this adapter.

All generation goes through `scripts/vibevoice_job.py`, which takes the same
exclusive `comfyui-runtime/state/gpu.lock` as Forge and H3. Direct
`voice_runtime/run.py tts` calls are rejected without the queue marker. Inference
is network-offline after model preparation and needs at least 5632 MiB free.
The 5.5 GiB placement cap keeps the diffusion head and model parameters on CUDA;
the model's custom sampler cannot run with its diffusion head CPU-offloaded.
Use short first samples and never overlap GPU inference.

## 3. Output and provenance

Successful jobs write:

```text
voice_runtime/outputs/<job_id>/
├── speech.wav
└── manifest.json
```

The manifest records model/source revisions, script and voice-reference SHA-256,
speakers, generation settings, sample rate and output SHA-256. It does not store
the full script text. The output folder is git-ignored.

## 4. Language and responsible use

The pinned 1.5B model card lists English and Chinese. **Portuguese is unsupported.**
The requested Portuguese generation is an internal experiment; inspect/listen to
the WAV before using it. The code/model cards are MIT-licensed, but the model
card states research-and-development as intended use and does not recommend
commercial or real-world deployment without further testing. See
[`reference/license-compliance.md`](../reference/license-compliance.md).

Every model-download and inference invocation requires `VIBEVOICE_RESEARCH_OK=1`.
This is an acknowledgment gate, not legal advice. Preserve VibeVoice's audible
AI disclosure and watermark. Voice cloning requires the speaker's explicit,
recorded consent; no impersonation of a real person.

## 5. Failure behavior

- Runtime not installed: run `./scripts/bootstrap_vibevoice.sh`; this does not
  fetch weights.
- Model not cached: review the model card, then run the explicit `prepare`
  command with `VIBEVOICE_RESEARCH_OK=1`.
- `status` reports `ready: false`: inspect dependency, source revision,
  disk-space, model-cache and free-VRAM fields in its JSON.
- Inference outside the shared GPU queue: use `scripts/vibevoice_job.py tts`.
- Out of memory: the full model remains on CUDA. Start with a short script and
  lower `--max-new-tokens`; free the GPU and retry only after checking the
  minimum-VRAM guard. Never run another GPU model at the same time.
- Portuguese pronunciation is poor: expected model limitation, not a failed
  installation. Do not present this unsupported-language sample as production
  quality.

## 6. Verified Portuguese smoke test

The pinned model generated a non-silent, mono 24 kHz WAV from a short
Brazilian Portuguese text prompt (seed 431, 256 output tokens, no reference
voice). No ASR or human pronunciation review was performed; Portuguese remains
unsupported and the result is not quality-validated.

The first attempt used a 5 GiB automatic placement cap. Accelerate offloaded the
diffusion head to CPU as `meta` parameters, but VibeVoice's custom sampler reads
that module's parameter device before calling its dispatch hook. The adapter now
keeps the model on CUDA with a 5.5 GiB placement cap and refuses inference below
5632 MiB free. Do not lower that placement cap or enable CPU offload.
