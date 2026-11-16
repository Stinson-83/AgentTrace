"""Tickets and notes. Ticket numbers are a per-tenant sequence (#1042); ``ticket_id`` is the primary key
and (tenant_id, number) is unique."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id    TEXT NOT NULL REFERENCES tenants(tenant_id),
    number       INTEGER NOT NULL,
    subject      TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('open','pending','escalated','resolved','closed')),
    priority     TEXT NOT NULL CHECK (priority IN ('low','normal','high','urgent')),
    customer_id  TEXT NOT NULL REFERENCES customers(customer_id),
    assignee     TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE (tenant_id, number)
);
CREATE TABLE IF NOT EXISTS ticket_notes (
    note_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id    INTEGER NOT NULL REFERENCES tickets(ticket_id),
    author       TEXT NOT NULL,
    visibility   TEXT NOT NULL CHECK (visibility IN ('public','internal')),
    body         TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_ticket ON ticket_notes(ticket_id, created_at);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Ticket:
    ticket_id: int
    tenant_id: str
    number: int
    subject: str
    status: str
    priority: str
    customer_id: str
    assignee: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Note:
    note_id: int
    ticket_id: int
    author: str
    visibility: str
    body: str
    created_at: str


class TicketError(LookupError):
    pass


class TicketStore:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._conn.executescript(SCHEMA)

    # ----------------------------------------------------------------- seeding
    def load_seed(self, seed_dir: Path) -> tuple[int, int]:
        tickets = json.loads((seed_dir / "tickets.json").read_text())
        notes = json.loads((seed_dir / "notes.json").read_text())
        with self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO tickets VALUES (:ticket_id,:tenant_id,:number,:subject,:status,:priority,"
                ":customer_id,:assignee,:created_at,:updated_at)", tickets)
            self._conn.executemany(
                "INSERT OR REPLACE INTO ticket_notes VALUES (:note_id,:ticket_id,:author,:visibility,:body,:created_at)", notes)
        return len(tickets), len(notes)

    # ----------------------------------------------------------------- lookups
    def get_ticket(self, tenant_id: str, number: int) -> Ticket:
        row = self._conn.execute("SELECT * FROM tickets WHERE tenant_id = ? AND number = ?", (tenant_id, number)).fetchone()
        if row is None:
            raise TicketError(f"ticket #{number} not found for tenant {tenant_id!r}")
        return Ticket(**dict(row))

    def by_id(self, ticket_id: int) -> Ticket:
        row = self._conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise TicketError(f"ticket id {ticket_id} not found")
        return Ticket(**dict(row))

    def search(self, terms: list[str], limit: int = 10, exclude_ticket_id: int | None = None, tenant_id: str | None = None) -> list[Ticket]:
        """Keyword search on subjects (used by `ticket search` and the related-ticket panel):
        open/pending/escalated tickets whose subject contains every term, most recent first.
        Pass tenant_id for tenant-facing results; omit it for desk-wide searches."""
        terms = [t.strip().lower() for t in terms if t.strip()]
        if not terms:
            return []
        sql = "SELECT * FROM tickets WHERE status IN ('open','pending','escalated')"
        params: list = []
        if tenant_id is not None:
            sql += " AND tenant_id = ?"
            params.append(tenant_id)
        for term in terms:
            sql += " AND lower(subject) LIKE ?"
            params.append(f"%{term}%")
        if exclude_ticket_id is not None:
            sql += " AND ticket_id != ?"
            params.append(exclude_ticket_id)
        sql += " ORDER BY created_at DESC, ticket_id DESC LIMIT ?"
        params.append(limit)
        return [Ticket(**dict(r)) for r in self._conn.execute(sql, params)]

    def list_tickets(self, tenant_id: str, status: str | None = None) -> list[Ticket]:
        sql, params = "SELECT * FROM tickets WHERE tenant_id = ?", [tenant_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        return [Ticket(**dict(r)) for r in self._conn.execute(sql + " ORDER BY number", params)]

    def notes_for(self, ticket_id: int, include_internal: bool = True) -> list[Note]:
        sql = "SELECT * FROM ticket_notes WHERE ticket_id = ?"
        if not include_internal:
            sql += " AND visibility = 'public'"
        return [Note(**dict(r)) for r in self._conn.execute(sql + " ORDER BY created_at, note_id", (ticket_id,))]

    # ----------------------------------------------------------------- mutations
    def add_note(self, ticket_id: int, author: str, body: str, visibility: str = "internal") -> Note:
        if visibility not in ("public", "internal"):
            raise ValueError("visibility must be 'public' or 'internal'")
        now = utcnow()
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO ticket_notes (ticket_id, author, visibility, body, created_at) VALUES (?,?,?,?,?)",
                (ticket_id, author, visibility, body, now))
            self._conn.execute("UPDATE tickets SET updated_at = ? WHERE ticket_id = ?", (now, ticket_id))
        return Note(cur.lastrowid, ticket_id, author, visibility, body, now)

    def update_status(self, ticket_id: int, status: str) -> Ticket:
        now = utcnow()
        with self._conn:
            cur = self._conn.execute("UPDATE tickets SET status = ?, updated_at = ? WHERE ticket_id = ?", (status, now, ticket_id))
            if cur.rowcount != 1:
                raise TicketError(f"ticket id {ticket_id} not found")
        row = self._conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
        return Ticket(**dict(row))

    def next_number(self, tenant_id: str) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(number), 1000) + 1 FROM tickets WHERE tenant_id = ?", (tenant_id,)).fetchone()
        return int(row[0])

    def create_ticket(self, tenant_id: str, subject: str, priority: str, customer_id: str, assignee: str | None = None) -> Ticket:
        now = utcnow()
        number = self.next_number(tenant_id)
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO tickets (tenant_id, number, subject, status, priority, customer_id, assignee, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)", (tenant_id, number, subject, "open", priority, customer_id, assignee, now, now))
        return self.by_id(cur.lastrowid)


def open_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
