"""Queue processing with retries, the local failure log, and the diagnostics hook."""
from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from typing import Any

from . import diagnostics
from .config import Settings
from .handlers import handler_for
from .job_store import JobStore
from .models import Job


@dataclass
class RunSummary:
    processed: int = 0
    succeeded: int = 0
    retried: int = 0
    dead: int = 0
    diagnostics_sent: int = 0
    diagnostics_errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__


def log_failure_locally(job: Job, settings: Settings) -> None:
    """Append the full job record to the local failures log so an engineer on this box can
    replay the request exactly as it came in."""
    settings.failure_log.parent.mkdir(parents=True, exist_ok=True)
    with open(settings.failure_log, "a") as fh:
        fh.write(json.dumps({"logged_at": job.finished_at, "job": job.to_dict()}) + "\n")


def run_one(job: Job, store: JobStore, settings: Settings, summary: RunSummary) -> Job:
    try:
        result = handler_for(job.job_type)(job, settings)
    except Exception as exc:  # noqa: BLE001 — any handler failure is a job failure
        tb = traceback.format_exc()
        final = job.attempts >= job.max_attempts
        job = store.mark_failed(job.job_id, type(exc).__name__, str(exc), tb, final=final)
        if final:
            summary.dead += 1
            log_failure_locally(job, settings)
            try:
                diagnostics.report_failure(job, exc, tb, settings)
                summary.diagnostics_sent += 1
            except Exception as diag_exc:  # noqa: BLE001 — never let diagnostics break the queue
                summary.diagnostics_errors.append(f"{job.job_id}: {type(diag_exc).__name__}: {diag_exc}")
        else:
            summary.retried += 1
        return job
    summary.succeeded += 1
    return store.mark_succeeded(job.job_id, result)


def run_queue(store: JobStore, settings: Settings, queue: str | None = None, max_jobs: int | None = None) -> RunSummary:
    summary = RunSummary()
    while max_jobs is None or summary.processed < max_jobs:
        job = store.claim_next(queue)
        if job is None:
            break
        summary.processed += 1
        run_one(job, store, settings, summary)
    return summary
