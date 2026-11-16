"""SQLite job store."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Job, RequestContext

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id             TEXT PRIMARY KEY,
    job_type           TEXT NOT NULL,
    queue              TEXT NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('pending','running','succeeded','failed','dead')),
    payload            TEXT NOT NULL,
    context            TEXT NOT NULL,
    attempts           INTEGER NOT NULL DEFAULT 0,
    max_attempts       INTEGER NOT NULL DEFAULT 3,
    enqueued_at        TEXT NOT NULL,
    started_at         TEXT,
    finished_at        TEXT,
    last_error_type    TEXT,
    last_error_message TEXT,
    last_traceback     TEXT,
    result             TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_queue ON jobs(status, queue, enqueued_at);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JobStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def load_seed(self, seed_dir: Path, replace: bool = False) -> int:
        rows = json.loads((seed_dir / "jobs.json").read_text())
        with self._conn:
            if replace:
                self._conn.execute("DELETE FROM jobs")
            for r in rows:
                self._conn.execute(
                    "INSERT OR REPLACE INTO jobs (job_id, job_type, queue, status, payload, context, attempts, max_attempts, enqueued_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (r["job_id"], r["job_type"], r["queue"], "pending", json.dumps(r["payload"]), json.dumps(r["context"]), 0, r.get("max_attempts", 3), r["enqueued_at"]))
        return len(rows)

    def enqueue(self, job_id: str, job_type: str, queue: str, payload: dict, context: RequestContext, max_attempts: int = 3) -> Job:
        now = utcnow()
        with self._conn:
            self._conn.execute(
                "INSERT INTO jobs (job_id, job_type, queue, status, payload, context, attempts, max_attempts, enqueued_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (job_id, job_type, queue, "pending", json.dumps(payload), json.dumps(context.as_dict()), 0, max_attempts, now))
        return self.get(job_id)

    def get(self, job_id: str) -> Job:
        row = self._conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown job {job_id!r}")
        return Job.from_row(dict(row))

    def list(self, status: str | None = None, queue: str | None = None) -> list[Job]:
        sql, params = "SELECT * FROM jobs WHERE 1=1", []
        if status:
            sql += " AND status = ?"; params.append(status)
        if queue:
            sql += " AND queue = ?"; params.append(queue)
        return [Job.from_row(dict(r)) for r in self._conn.execute(sql + " ORDER BY enqueued_at, job_id", params)]

    def claim_next(self, queue: str | None = None) -> Job | None:
        sql, params = "SELECT job_id FROM jobs WHERE status = 'pending'", []
        if queue:
            sql += " AND queue = ?"; params.append(queue)
        row = self._conn.execute(sql + " ORDER BY enqueued_at, job_id LIMIT 1", params).fetchone()
        if row is None:
            return None
        with self._conn:
            self._conn.execute("UPDATE jobs SET status = 'running', started_at = ?, finished_at = NULL, attempts = attempts + 1 WHERE job_id = ?", (utcnow(), row["job_id"]))
        return self.get(row["job_id"])

    def mark_succeeded(self, job_id: str, result: dict) -> Job:
        with self._conn:
            self._conn.execute("UPDATE jobs SET status = 'succeeded', finished_at = ?, result = ?, last_error_type = NULL, last_error_message = NULL, last_traceback = NULL WHERE job_id = ?",
                               (utcnow(), json.dumps(result), job_id))
        return self.get(job_id)

    def mark_failed(self, job_id: str, error_type: str, message: str, traceback_text: str, final: bool) -> Job:
        with self._conn:
            self._conn.execute(
                "UPDATE jobs SET status = ?, finished_at = ?, last_error_type = ?, last_error_message = ?, last_traceback = ? WHERE job_id = ?",
                ("dead" if final else "pending", utcnow(), error_type, message[:2000], traceback_text[-8000:], job_id))
        return self.get(job_id)

    def requeue(self, job_id: str, reset_attempts: bool = True) -> Job:
        """Put a dead (or failed) job back on the queue for another run."""
        job = self.get(job_id)
        if job.status not in ("dead", "pending"):
            raise ValueError(f"job {job_id} is {job.status}; only dead jobs can be requeued")
        with self._conn:
            self._conn.execute("UPDATE jobs SET status = 'pending', attempts = CASE WHEN ? THEN 0 ELSE attempts END, started_at = NULL, finished_at = NULL WHERE job_id = ?",
                               (1 if reset_attempts else 0, job_id))
        return self.get(job_id)

    def failure_breakdown(self) -> dict[str, dict[str, int]]:
        """Dead jobs grouped by error type and by queue (what the weekly triage looks at)."""
        by_error: dict[str, int] = {}
        by_queue: dict[str, int] = {}
        for r in self._conn.execute("SELECT last_error_type, queue, COUNT(*) AS n FROM jobs WHERE status = 'dead' GROUP BY last_error_type, queue"):
            by_error[r["last_error_type"] or "unknown"] = by_error.get(r["last_error_type"] or "unknown", 0) + r["n"]
            by_queue[r["queue"]] = by_queue.get(r["queue"], 0) + r["n"]
        return {"by_error_type": dict(sorted(by_error.items())), "by_queue": dict(sorted(by_queue.items()))}

    def counts(self) -> dict[str, int]:
        return {r["status"]: r["n"] for r in self._conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status ORDER BY status")}
