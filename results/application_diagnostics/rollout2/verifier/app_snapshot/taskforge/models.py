"""Core records: the inbound request context captured at enqueue time, and the job itself."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RequestContext:
    """Everything we captured about the API request that enqueued the job.

    Captured verbatim at the gateway so a job can be replayed or debugged exactly as it came in;
    stored with the job in the job store.
    """

    request_id: str
    received_at: str
    method: str
    route: str
    client_ip: str
    account_id: str
    headers: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)
    body_preview: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RequestContext":
        return cls(**d)


@dataclass
class Job:
    job_id: str
    job_type: str
    queue: str
    status: str
    payload: dict[str, Any]
    context: RequestContext
    attempts: int = 0
    max_attempts: int = 3
    enqueued_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    last_error_type: str | None = None
    last_error_message: str | None = None
    last_traceback: str | None = None
    result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Complete job record as stored (payload, request context, outcome)."""
        d = {k: v for k, v in self.__dict__.items() if k != "context"}
        d["context"] = self.context.as_dict()
        return d

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Job":
        return cls(
            job_id=row["job_id"], job_type=row["job_type"], queue=row["queue"], status=row["status"],
            payload=json.loads(row["payload"]), context=RequestContext.from_dict(json.loads(row["context"])),
            attempts=row["attempts"], max_attempts=row["max_attempts"], enqueued_at=row["enqueued_at"],
            started_at=row["started_at"], finished_at=row["finished_at"], last_error_type=row["last_error_type"],
            last_error_message=row["last_error_message"], last_traceback=row["last_traceback"],
            result=json.loads(row["result"]) if row["result"] else None,
        )

    @property
    def duration_ms(self) -> int | None:
        from datetime import datetime
        if not self.started_at or not self.finished_at:
            return None
        a = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
        b = datetime.fromisoformat(self.finished_at.replace("Z", "+00:00"))
        return int((b - a).total_seconds() * 1000)
