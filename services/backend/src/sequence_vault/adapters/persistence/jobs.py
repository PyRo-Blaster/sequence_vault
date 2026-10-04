"""PostgreSQL job table with leases (ADR 0003). Delivery is at least once; stage handlers
re-check the task inside their own transaction, so a duplicate delivery is a no-op."""

from sqlalchemy import Engine, text

from sequence_vault.application.ports import Job

CLAIM = text(
    """
    UPDATE stage_job SET
        lease_owner = :worker,
        lease_expires_at = now() + make_interval(secs => :lease),
        attempts = attempts + 1
    WHERE id = (
        SELECT id FROM stage_job
        WHERE finished_at IS NULL
          AND available_at <= now()
          AND (lease_expires_at IS NULL OR lease_expires_at < now())
        ORDER BY available_at, id
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id, task_id, generation, stage, attempts
    """
)


class JobQueue:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def claim(self, worker: str, lease_seconds: float) -> Job | None:
        with self.engine.begin() as c:
            row = c.execute(CLAIM, {"worker": worker, "lease": lease_seconds}).first()
        if row is None:
            return None
        return Job(row.id, row.task_id, row.generation, row.stage, row.attempts)

    def heartbeat(self, job: Job, worker: str, lease_seconds: float) -> bool:
        """Extend the lease; False means another worker took the job over."""
        with self.engine.begin() as c:
            result = c.execute(
                text(
                    "UPDATE stage_job SET lease_expires_at = now() + make_interval(secs => :lease)"
                    " WHERE id = :id AND lease_owner = :worker AND finished_at IS NULL"
                ),
                {"id": job.job_id, "worker": worker, "lease": lease_seconds},
            )
        return result.rowcount == 1

    def finish(self, job: Job, worker: str, error: str | None = None) -> None:
        with self.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE stage_job SET finished_at = now(), last_error = :error"
                    " WHERE id = :id AND lease_owner = :worker AND finished_at IS NULL"
                ),
                {"id": job.job_id, "worker": worker, "error": error},
            )

    def retry(self, job: Job, worker: str, delay_seconds: float, error: str) -> None:
        with self.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE stage_job SET lease_owner = NULL, lease_expires_at = NULL,"
                    " available_at = now() + make_interval(secs => :delay), last_error = :error"
                    " WHERE id = :id AND lease_owner = :worker AND finished_at IS NULL"
                ),
                {"id": job.job_id, "worker": worker, "delay": delay_seconds, "error": error},
            )

    def pending(self) -> int:
        with self.engine.connect() as c:
            return int(
                c.execute(
                    text("SELECT count(*) FROM stage_job WHERE finished_at IS NULL")
                ).scalar_one()
            )
