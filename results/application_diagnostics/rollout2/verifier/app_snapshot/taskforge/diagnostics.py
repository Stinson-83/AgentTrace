"""Failure diagnostics for the engineering observability service (ops-observe).

See docs/observability_events.md for the event contract.
"""
from __future__ import annotations

import re
from typing import Any

from .config import Settings
from .models import Job
from .observability_client import ObservabilityClient

_FRAME_RE = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<function>\S+)')


def stack_summary(traceback_text: str, frames: int = 5) -> list[dict[str, Any]]:
    """The innermost ``frames`` frames of a formatted traceback as (file, line, function) entries,
    innermost last. Only frame locations — never locals or source."""
    found = []
    for line in traceback_text.splitlines():
        m = _FRAME_RE.match(line)
        if m:
            found.append({"file": m.group("file").split("/")[-1], "line": int(m.group("line")), "function": m.group("function")})
    return found[-frames:]


def truncate(text: str | None, limit: int = 500) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def report_failure(job: Job, exc: BaseException, traceback_text: str, settings: Settings) -> dict[str, Any]:
    """Build the ``job.failed`` diagnostic event for a job that has exhausted its attempts and
    send it to ops-observe. Returns the event that was sent.

    Only triage identifiers and value-free error summaries leave the worker. The full request,
    payload, error text and traceback remain in the local failure log for replay/debugging.
    Delivery errors propagate to the runner's diagnostics error accounting.
    """
    event = {
        "event_type": "job.failed",
        "service": settings.service_name,
        "environment": settings.environment,
        "job_id": job.job_id,
        "job_type": job.job_type,
        "queue": job.queue,
        "failed_at": job.finished_at,
        "attempt": job.attempts,
        "error_type": type(exc).__name__,
        "error_message": truncate(getattr(exc, "summary", None) or type(exc).__name__),
        "stack_summary": stack_summary(traceback_text),
        "request": {
            "request_id": job.context.request_id,
            "account_id": job.context.account_id,
            "route": job.context.route,
        },
        "duration_ms": job.duration_ms,
    }
    client = ObservabilityClient(settings.observe_url, settings.observe_timeout_sec, settings.service_name)
    client.post_events([event])
    return event
