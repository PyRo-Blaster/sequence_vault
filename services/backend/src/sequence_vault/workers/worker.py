"""Worker loop: claim a stage job, keep its lease alive, run it, then finish or retry."""

import logging
import random
import threading
from collections.abc import Callable
from typing import Protocol

from sequence_vault.application.ports import Job, TransientError

log = logging.getLogger("sequence_vault.worker")


class Queue(Protocol):
    def claim(self, worker: str, lease_seconds: float) -> Job | None: ...
    def heartbeat(self, job: Job, worker: str, lease_seconds: float) -> bool: ...
    def finish(self, job: Job, worker: str, error: str | None = None) -> None: ...
    def retry(self, job: Job, worker: str, delay_seconds: float, error: str) -> None: ...


class Stages(Protocol):
    def handle(self, job: Job) -> None: ...
    def give_up(self, job: Job, failure_code: str) -> None: ...


def backoff(attempt: int, *, base: float = 2.0, cap: float = 300.0) -> float:
    """Exponential backoff with full jitter."""
    return random.uniform(0, min(cap, base * 2 ** (attempt - 1)))


class Worker:
    def __init__(
        self,
        queue: Queue,
        stages: Stages,
        *,
        worker_id: str,
        lease_seconds: float = 60.0,
        max_transient_retries: int = 3,
        delay: Callable[[int], float] = backoff,
    ) -> None:
        self.queue = queue
        self.stages = stages
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.max_transient_retries = max_transient_retries
        self.delay = delay

    def run_once(self) -> bool:
        """Process one job; False when nothing was ready."""
        job = self.queue.claim(self.worker_id, self.lease_seconds)
        if job is None:
            return False
        done = threading.Event()
        beat = threading.Thread(target=self._heartbeat, args=(job, done), daemon=True)
        beat.start()
        try:
            self.stages.handle(job)
        except TransientError as error:
            if job.attempts > self.max_transient_retries:
                log.warning("job %s gave up after %s attempts", job.job_id, job.attempts)
                self.stages.give_up(job, _code(job, "unavailable"))
                self.queue.finish(job, self.worker_id, type(error).__name__)
            else:
                self.queue.retry(
                    job, self.worker_id, self.delay(job.attempts), type(error).__name__
                )
        except Exception as error:  # an unexpected error must not loop forever
            log.exception("job %s failed", job.job_id)
            self.stages.give_up(job, "internal_error")
            self.queue.finish(job, self.worker_id, type(error).__name__)
        else:
            self.queue.finish(job, self.worker_id)
        finally:
            done.set()
            beat.join()
        return True

    def run_until_idle(self, max_jobs: int = 10_000) -> int:
        processed = 0
        while processed < max_jobs and self.run_once():
            processed += 1
        return processed

    def run_forever(self, stop: threading.Event, idle_sleep: float = 1.0) -> None:
        while not stop.is_set():
            if not self.run_once():
                stop.wait(idle_sleep)

    def _heartbeat(self, job: Job, done: threading.Event) -> None:
        while not done.wait(self.lease_seconds / 3):
            if not self.queue.heartbeat(job, self.worker_id, self.lease_seconds):
                log.warning("lost the lease on job %s", job.job_id)
                return


def _code(job: Job, suffix: str) -> str:
    return {"SCANNING": "scan", "PARSING": "parse", "EXTRACTING": "extract"}.get(
        job.stage, "stage"
    ) + f"_{suffix}"
