# License Compliance

The [MiniMax H3 Community License](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE)
and other model terms may vary by revision, region and intended deployment.
Review the current source license for the user's jurisdiction and use case.

## Required behavior

- Never download H3 weights without an explicit user confirmation that the
  applicable separate license is granted.
- Keep the `LICENSE_OK=1` gate in `fetch_h3_weights.sh`.
- Store any license evidence only in the user's approved private audit system;
  never add grants, identity or location details to this repository.
- Do not claim commercial rights for generated outputs unless the user's
  license covers them.
- Distinguish local open-weight inference from hosted API terms.

## Download gate

```bash
LICENSE_OK=1 ./comfyui-runtime/fetch_h3_weights.sh
```

The gate is an operational safeguard, not legal advice. Users remain
responsible for reviewing the current license before downloading or deploying.

## VibeVoice

The [community source repository](https://github.com/vibevoice-community/VibeVoice)
and the pinned [VibeVoice 1.5B HF model card](https://huggingface.co/vibevoice/VibeVoice-1.5B-hf)
list MIT licensing. The model card nevertheless describes research and
development as the intended use and does not recommend commercial or real-world
use without further testing. Treat the model as research-only until the
intended deployment is separately reviewed; MIT metadata is not a commercial
fitness assessment.

Required safeguards:

- The local CLI requires `VIBEVOICE_RESEARCH_OK=1` on both model preparation and
  inference. This is an acknowledgment gate, not legal advice or a grant of
  rights.
- The pinned 1.5B model card lists English and Chinese. Portuguese is
  unsupported; only run the requested Portuguese sample as an internal
  experiment and review it manually.
- Use voice-reference audio only with the speaker's explicit, recorded consent.
  Do not impersonate a real person or present generated audio as authentic.
- Preserve the model's audible disclosure and watermark. Do not remove or bypass
  them.

The explicit model download command is:

```bash
VIBEVOICE_RESEARCH_OK=1 python voice_runtime/run.py prepare
```
