#!/usr/bin/env python3
"""Small persistent FIFO registry and exclusive GPU runner."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "comfyui-runtime" / "state"
JOBS = STATE / "jobs.json"
LOCK = STATE / "gpu.lock"


def now() -> float:
    return time.time()


def read_jobs() -> dict:
    if not JOBS.exists():
        return {}
    try:
        return json.loads(JOBS.read_text())
    except json.JSONDecodeError:
        return {}


def write_jobs(jobs: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="jobs.", dir=STATE)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(jobs, f, indent=2)
            f.write("\n")
        os.replace(name, JOBS)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def recover_orphans(jobs: dict) -> bool:
    changed = False
    for job in jobs.values():
        if job.get("status") != "running":
            continue
        pid = job.get("pid")
        alive = False
        if pid:
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False
        if not alive:
            job["status"] = "interrupted"
            job["finished_at"] = now()
            changed = True
    return changed


def new_job(kind: str, payload: dict) -> dict:
    job_id = f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    return {"job_id": job_id, "kind": kind, "status": "queued",
            "created_at": now(), "payload": payload, "pid": None}


def enqueue(args: argparse.Namespace) -> int:
    jobs = read_jobs()
    recover_orphans(jobs)
    job = new_job(args.kind, json.loads(args.payload))
    jobs[job["job_id"]] = job
    write_jobs(jobs)
    print(json.dumps(job, indent=2))
    return 0


def list_jobs(_: argparse.Namespace) -> int:
    jobs = read_jobs()
    if recover_orphans(jobs):
        write_jobs(jobs)
    print(json.dumps(list(jobs.values()), indent=2))
    return 0


def status(args: argparse.Namespace) -> int:
    jobs = read_jobs()
    if recover_orphans(jobs):
        write_jobs(jobs)
    job = jobs.get(args.job_id)
    if not job:
        print(json.dumps({"error": "job_not_found", "job_id": args.job_id}))
        return 1
    print(json.dumps(job, indent=2))
    return 0


def cancel(args: argparse.Namespace) -> int:
    jobs = read_jobs()
    job = jobs.get(args.job_id)
    if not job:
        print(json.dumps({"error": "job_not_found", "job_id": args.job_id}))
        return 1
    if job["status"] != "queued":
        print(json.dumps({"error": "only_queued_jobs_are_cancellable", "job": job}, indent=2))
        return 1
    job["status"] = "cancelled"
    job["finished_at"] = now()
    write_jobs(jobs)
    print(json.dumps(job, indent=2))
    return 0


def run(args: argparse.Namespace) -> int:
    if not args.command:
        raise SystemExit("run requires -- command")
    jobs = read_jobs()
    job = new_job(args.kind, {"command": args.command})
    jobs[job["job_id"]] = job
    write_jobs(jobs)
    final_status = "failed"

    STATE.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as lock:
        print(json.dumps({"job_id": job["job_id"], "status": "queued"}, indent=2), flush=True)
        fcntl.flock(lock, fcntl.LOCK_EX)
        jobs = read_jobs()
        jobs[job["job_id"]].update({"status": "running", "started_at": now(), "pid": os.getpid()})
        write_jobs(jobs)
        try:
            env = os.environ.copy()
            env["POSTWARD_JOB_ID"] = job["job_id"]
            env["POSTWARD_GPU_LOCK_HELD"] = "1"
            proc = subprocess.run(args.command, env=env)
            final_status = "success" if proc.returncode == 0 else "failed"
            returncode = proc.returncode
        except KeyboardInterrupt:
            final_status = "cancelled"
            returncode = 130
            raise
        finally:
            jobs = read_jobs()
            jobs[job["job_id"]].update({"status": final_status,
                                          "returncode": returncode,
                                          "finished_at": now(), "pid": None})
            write_jobs(jobs)
    return 0 if final_status == "success" else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="action", required=True)
    p = sub.add_parser("enqueue")
    p.add_argument("--kind", required=True)
    p.add_argument("--payload", default="{}")
    p.set_defaults(fn=enqueue)
    p = sub.add_parser("list")
    p.set_defaults(fn=list_jobs)
    p = sub.add_parser("status")
    p.add_argument("job_id")
    p.set_defaults(fn=status)
    p = sub.add_parser("cancel")
    p.add_argument("job_id")
    p.set_defaults(fn=cancel)
    p = sub.add_parser("run")
    p.add_argument("--kind", required=True)
    p.add_argument("command", nargs=argparse.REMAINDER)
    p.set_defaults(fn=run)
    args = ap.parse_args()
    if getattr(args, "command", None) and args.command[0] == "--":
        args.command = args.command[1:]
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
