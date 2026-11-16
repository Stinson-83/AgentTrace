"""SQLite-backed storage for customers and transactions."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id    TEXT PRIMARY KEY,
    full_name      TEXT NOT NULL,
    email          TEXT NOT NULL,
    phone          TEXT,
    date_of_birth  TEXT,
    tax_reference  TEXT,
    country        TEXT NOT NULL,
    segment        TEXT NOT NULL,
    currency       TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    txn_id        TEXT PRIMARY KEY,
    customer_id   TEXT NOT NULL REFERENCES customers(customer_id),
    occurred_at   TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('sale', 'refund')),
    amount_cents  INTEGER NOT NULL CHECK (amount_cents >= 0),
    currency      TEXT NOT NULL,
    channel       TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('settled', 'pending', 'declined'))
);
CREATE INDEX IF NOT EXISTS idx_txn_customer_time ON transactions(customer_id, occurred_at);
"""


@dataclass(frozen=True)
class Customer:
    customer_id: str
    full_name: str
    email: str
    phone: str | None
    date_of_birth: str | None
    tax_reference: str | None
    country: str
    segment: str
    currency: str
    created_at: str


@dataclass(frozen=True)
class Transaction:
    txn_id: str
    customer_id: str
    occurred_at: str
    kind: str
    amount_cents: int
    currency: str
    channel: str
    status: str

    @property
    def occurred_on(self) -> date:
        return datetime.fromisoformat(self.occurred_at.replace("Z", "+00:00")).date()

    @property
    def signed_amount_cents(self) -> int:
        return -self.amount_cents if self.kind == "refund" else self.amount_cents


class StoreError(RuntimeError):
    pass


class CustomerStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ seeding
    def load_seed(self, seed_dir: Path, replace: bool = False) -> tuple[int, int]:
        customers = json.loads((seed_dir / "customers.json").read_text())
        transactions = json.loads((seed_dir / "transactions.json").read_text())
        with self._conn:
            if replace:
                self._conn.execute("DELETE FROM transactions")
                self._conn.execute("DELETE FROM customers")
            self._conn.executemany(
                "INSERT OR REPLACE INTO customers VALUES (:customer_id,:full_name,:email,:phone,"
                ":date_of_birth,:tax_reference,:country,:segment,:currency,:created_at)",
                customers,
            )
            self._conn.executemany(
                "INSERT OR REPLACE INTO transactions VALUES (:txn_id,:customer_id,:occurred_at,:kind,"
                ":amount_cents,:currency,:channel,:status)",
                transactions,
            )
        return len(customers), len(transactions)

    # ---------------------------------------------------------------- customers
    def get_customer(self, customer_id: str) -> Customer:
        row = self._conn.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
        if row is None:
            raise StoreError(f"unknown customer {customer_id!r}")
        return Customer(**dict(row))

    def list_customers(self, segment: str | None = None) -> list[Customer]:
        sql, params = "SELECT * FROM customers", ()
        if segment:
            sql, params = sql + " WHERE segment = ?", (segment,)
        rows = self._conn.execute(sql + " ORDER BY customer_id", params).fetchall()
        return [Customer(**dict(r)) for r in rows]

    def count_customers(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0])

    # ------------------------------------------------------------- transactions
    def transactions_for(self, customer_id: str) -> list[Transaction]:
        rows = self._conn.execute(
            "SELECT * FROM transactions WHERE customer_id = ? ORDER BY occurred_at, txn_id", (customer_id,)
        ).fetchall()
        return [Transaction(**dict(r)) for r in rows]

    def transactions_between(self, start: date, end_exclusive: date) -> Iterator[Transaction]:
        """All transactions with start <= occurred_at < end_exclusive (UTC dates)."""
        rows = self._conn.execute(
            "SELECT * FROM transactions WHERE occurred_at >= ? AND occurred_at < ? ORDER BY occurred_at, txn_id",
            (f"{start.isoformat()}T00:00:00Z", f"{end_exclusive.isoformat()}T00:00:00Z"),
        )
        for r in rows:
            yield Transaction(**dict(r))

    def add_transactions(self, txns: Iterable[Transaction]) -> int:
        rows = [t.__dict__ for t in txns]
        with self._conn:
            self._conn.executemany(
                "INSERT INTO transactions VALUES (:txn_id,:customer_id,:occurred_at,:kind,"
                ":amount_cents,:currency,:channel,:status)",
                rows,
            )
        return len(rows)
