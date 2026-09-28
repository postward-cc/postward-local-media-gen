# Concurrency and Job Lifecycle

## Policy

One GPU inference job at a time. Multiple logical requests are accepted through
the persistent queue. CPU-only ffmpeg work may run concurrently when resources
allow.

Forge SDXL, ComfyUI/H3 and VibeVoice share the **same** exclusive GPU lease.
`scripts/forge_job.py` and `scripts/vibevoice_job.py` invoke
`job_queue.py run`; do not call an inference CLI directly. The queue passes
`POSTWARD_GPU_LOCK_HELD` and `POSTWARD_JOB_ID` only after acquiring
`comfyui-runtime/state/gpu.lock`.

Forge may run idle as an API server, but do not submit Forge, VibeVoice or H3
inference while another GPU inference owns the lease. `job_queue.py enqueue`
records metadata only; it is not a background dispatcher. Use the synchronous
`run` path for actual inference.

## Lifecycle

```text
queued → running → success
                 ├→ failed
                 ├→ cancelled
                 └→ interrupted
```

Every job gets a unique directory under `state/jobs/<job_id>/` or the configured
output root. Never share a generic `output.mp4` between jobs.

## Orphan recovery

On startup or `doctor.py`, a `running` job whose PID no longer exists becomes
`interrupted`. The GPU lease is then eligible for a new job.

## Fairness

Default FIFO. A priority flag may be added later, but interactive requests
must not starve a long queued batch. Cancellation is allowed for queued jobs;
running jobs are terminated only by explicit user request.

## Why not run two H3 jobs?

The 8 GB profile stages roughly 20 GB of diffusion weights and 15 GB of text
encoder weights in system RAM while swapping active layers through the GPU.
Launching a second sampler destroys the VRAM budget and usually produces OOM or
unusable swap thrashing.
