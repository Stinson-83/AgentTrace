"""Failure diagnostics for the engineering observability service (ops-observe).

See docs/observability_events.md for the event contract.
"""
from __future__ import annotations

import re
from typing import Any

from .config import Settings
from .models import Job

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

    Not implemented yet — see ticket TF-642.
    """
    raise NotImplementedError("failure diagnostics are not wired up yet (TF-642)")
