from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "job_queue", ROOT / "scripts" / "job_queue.py")
job_queue = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(job_queue)


class QueueStateTests(unittest.TestCase):
    """The queue keeps its own state; tests must never touch the real one."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        for name, value in (("STATE", root), ("JOBS", root / "jobs.json"),
                            ("LOCK", root / "gpu.lock")):
            original = getattr(job_queue, name)
            setattr(job_queue, name, value)
            self.addCleanup(setattr, job_queue, name, original)


def queue_args(**kwargs):
    return argparse.Namespace(**kwargs)


class OrphanRecoveryTests(QueueStateTests):
    def test_running_job_whose_process_is_gone_becomes_interrupted(self):
        jobs = {"a": {"status": "running", "pid": 2 ** 22}}

        changed = job_queue.recover_orphans(jobs)

        self.assertTrue(changed)
        self.assertEqual(jobs["a"]["status"], "interrupted")
        self.assertIn("finished_at", jobs["a"])

    def test_running_job_with_a_live_process_is_left_alone(self):
        jobs = {"a": {"status": "running", "pid": os.getpid()}}

        changed = job_queue.recover_orphans(jobs)

        self.assertFalse(changed)
        self.assertEqual(jobs["a"]["status"], "running")

    def test_only_running_jobs_are_recovered(self):
        jobs = {"a": {"status": "success", "pid": 2 ** 22},
                "b": {"status": "queued", "pid": 2 ** 22},
                "c": {"status": "running", "pid": 2 ** 22}}

        job_queue.recover_orphans(jobs)

        self.assertEqual(jobs["a"]["status"], "success")
        self.assertEqual(jobs["b"]["status"], "queued")
        self.assertEqual(jobs["c"]["status"], "interrupted")


class RunContractTests(QueueStateTests):
    def test_child_command_is_told_it_holds_the_gpu_lock(self):
        args = queue_args(kind="forge-txt2img",
                          command=[sys.executable, "-c",
                                   "import os;print(os.environ['POSTWARD_GPU_LOCK_HELD'])"])

        returncode = job_queue.run(args)

        self.assertEqual(returncode, 0)
        job = next(iter(json.loads(job_queue.JOBS.read_text()).values()))
        self.assertEqual(job["status"], "success")

    def test_failed_command_is_recorded_as_failed_with_its_returncode(self):
        args = queue_args(kind="forge-txt2img",
                          command=[sys.executable, "-c", "raise SystemExit(3)"])

        returncode = job_queue.run(args)

        self.assertEqual(returncode, 1)
        job = next(iter(json.loads(job_queue.JOBS.read_text()).values()))
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["returncode"], 3)
        self.assertIsNone(job["pid"])

    def test_a_second_run_waits_for_the_lock_instead_of_running_concurrently(self):
        """The concurrency contract: one GPU inference job at a time.

        Two distinct descriptors on the same file do conflict under flock, so a
        thread models the second worker faithfully without a subprocess and
        without a state-directory override in production code.
        """
        marker = Path(self.directory.name) / "ran.txt"
        holder = job_queue.LOCK.open("w")
        self.addCleanup(holder.close)
        fcntl.flock(holder, fcntl.LOCK_EX)

        outcome = {}

        def worker():
            started = time.monotonic()
            args = queue_args(kind="forge-txt2img",
                              command=[sys.executable, "-c",
                                       f"open({str(marker)!r}, 'w').write('x')"])
            outcome["returncode"] = job_queue.run(args)
            outcome["waited"] = time.monotonic() - started

        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(1)
        self.assertFalse(marker.exists(), "second job ran while the lease was held")
        self.assertTrue(thread.is_alive(), "second job did not block on the lease")

        fcntl.flock(holder, fcntl.LOCK_UN)
        thread.join(timeout=30)

        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome["returncode"], 0)
        self.assertTrue(marker.exists(), "second job never ran after the lease was released")


class CancelTests(QueueStateTests):
    def test_queued_job_can_be_cancelled(self):
        job = job_queue.new_job("h3-t2v", {"command": []})
        job_queue.write_jobs({job["job_id"]: job})

        returncode = job_queue.cancel(queue_args(job_id=job["job_id"]))

        self.assertEqual(returncode, 0)
        self.assertEqual(job_queue.read_jobs()[job["job_id"]]["status"], "cancelled")

    def test_running_job_cannot_be_cancelled(self):
        job = job_queue.new_job("h3-t2v", {"command": []})
        job["status"] = "running"
        job_queue.write_jobs({job["job_id"]: job})

        returncode = job_queue.cancel(queue_args(job_id=job["job_id"]))

        self.assertEqual(returncode, 1)
        self.assertEqual(job_queue.read_jobs()[job["job_id"]]["status"], "running")


if __name__ == "__main__":
    unittest.main()