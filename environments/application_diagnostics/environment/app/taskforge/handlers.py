"""Job handlers. Each handler takes (job, settings) and returns a result dict or raises."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .models import Job

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


class HandlerError(RuntimeError):
    """Base class for job failures that are the job's fault (retryable or not)."""


class DeliveryError(HandlerError):
    pass


class RenderError(HandlerError):
    pass


class ImportValidationError(HandlerError):
    pass


def _out(settings: Settings, *parts: str) -> Path:
    path = settings.output_dir.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def deliver_webhook(job: Job, settings: Settings) -> dict[str, Any]:
    """Deliver an outbound webhook. The transport is simulated locally: deliveries are written to
    ``output/webhooks/`` and hosts under ``.invalid`` fail with a connection error."""
    url = str(job.payload.get("url", ""))
    event = job.payload.get("event")
    if not url.startswith("https://"):
        raise DeliveryError(f"refusing to deliver to non-https url {url!r}")
    if not isinstance(event, dict) or "type" not in event:
        raise DeliveryError("webhook event must be an object with a 'type'")
    host = url.split("/", 3)[2]
    if host.endswith(".invalid"):
        raise DeliveryError(f"POST {url} failed: name or service not known ({host})")
    path = _out(settings, "webhooks", f"{job.job_id}.json")
    path.write_text(json.dumps({"url": url, "event": event, "attempt": job.attempts}, indent=2))
    return {"delivered_to": host, "bytes": path.stat().st_size}


def render_report(job: Job, settings: Settings) -> dict[str, Any]:
    """Render a usage report for an account/period into ``output/reports/``."""
    period = str(job.payload.get("period", ""))
    try:
        datetime.strptime(period, "%Y-%m")
    except ValueError:
        raise RenderError(f"period must be YYYY-MM, got {period!r}") from None
    rows = job.payload.get("rows") or []
    lines = ["metric,value"] + [f"{r['metric']},{r['value']}" for r in rows]
    path = _out(settings, "reports", f"{job.payload.get('report', 'report')}-{job.context.account_id}-{period}.csv")
    path.write_text("\n".join(lines) + "\n")
    return {"path": str(path), "rows": len(rows)}


def import_contacts(job: Job, settings: Settings) -> dict[str, Any]:
    """Validate and store a contact import batch under ``output/imports/``."""
    rows = job.payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ImportValidationError("import batch has no rows")
    invalid = [i for i, r in enumerate(rows) if not isinstance(r, dict) or not _EMAIL_RE.match(str(r.get("email", "")))]
    if invalid:
        raise ImportValidationError(f"{len(invalid)} of {len(rows)} rows have an invalid e-mail; first bad row {invalid[0]}: {rows[invalid[0]]!r}")
    path = _out(settings, "imports", f"{job.job_id}.json")
    path.write_text(json.dumps({"account_id": job.context.account_id, "rows": rows}, indent=2))
    return {"imported": len(rows), "path": str(path)}


HANDLERS: dict[str, Callable[[Job, Settings], dict[str, Any]]] = {
    "webhook.deliver": deliver_webhook,
    "report.render": render_report,
    "contacts.import": import_contacts,
}


class UnknownJobType(HandlerError):
    pass


def handler_for(job_type: str) -> Callable[[Job, Settings], dict[str, Any]]:
    try:
        return HANDLERS[job_type]
    except KeyError:
        raise UnknownJobType(f"no handler registered for job type {job_type!r}") from None
