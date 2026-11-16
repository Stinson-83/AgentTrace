"""SQLite store for merchants and settlements."""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from .models import MerchantAccount, Settlement

SCHEMA = """
CREATE TABLE IF NOT EXISTS merchants (
    merchant_id TEXT PRIMARY KEY, legal_name TEXT NOT NULL, trading_name TEXT NOT NULL, country TEXT NOT NULL,
    currency TEXT NOT NULL, settlement_reference TEXT NOT NULL UNIQUE, iban TEXT NOT NULL, account_number TEXT NOT NULL,
    sort_code TEXT NOT NULL, bank_name TEXT NOT NULL, vat_number TEXT, contact_email TEXT NOT NULL, onboarded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settlements (
    settlement_id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(merchant_id), settled_on TEXT NOT NULL,
    currency TEXT NOT NULL, gross_cents INTEGER NOT NULL, fees_cents INTEGER NOT NULL, refunds_cents INTEGER NOT NULL,
    transaction_count INTEGER NOT NULL, status TEXT NOT NULL CHECK (status IN ('paid','pending','reversed'))
);
CREATE INDEX IF NOT EXISTS idx_settlements_merchant_day ON settlements(merchant_id, settled_on);
"""


class LedgerError(LookupError):
    pass


class LedgerStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def load_seed(self, seed_dir: Path, replace: bool = False) -> tuple[int, int]:
        merchants = json.loads((seed_dir / "merchants.json").read_text())
        settlements = json.loads((seed_dir / "settlements.json").read_text())
        with self._conn:
            if replace:
                self._conn.execute("DELETE FROM settlements")
                self._conn.execute("DELETE FROM merchants")
            self._conn.executemany(
                "INSERT OR REPLACE INTO merchants VALUES (:merchant_id,:legal_name,:trading_name,:country,:currency,:settlement_reference,"
                ":iban,:account_number,:sort_code,:bank_name,:vat_number,:contact_email,:onboarded_at)", merchants)
            self._conn.executemany(
                "INSERT OR REPLACE INTO settlements VALUES (:settlement_id,:merchant_id,:settled_on,:currency,:gross_cents,:fees_cents,"
                ":refunds_cents,:transaction_count,:status)", settlements)
        return len(merchants), len(settlements)

    def merchant(self, merchant_id: str) -> MerchantAccount:
        row = self._conn.execute("SELECT * FROM merchants WHERE merchant_id = ?", (merchant_id,)).fetchone()
        if row is None:
            raise LedgerError(f"unknown merchant {merchant_id!r}")
        return MerchantAccount(**dict(row))

    def merchants(self) -> list[MerchantAccount]:
        return [MerchantAccount(**dict(r)) for r in self._conn.execute("SELECT * FROM merchants ORDER BY merchant_id")]

    def settlements_between(self, start: date, end_exclusive: date, merchant_id: str | None = None) -> list[Settlement]:
        sql, params = "SELECT * FROM settlements WHERE settled_on >= ? AND settled_on < ?", [start.isoformat(), end_exclusive.isoformat()]
        if merchant_id:
            sql += " AND merchant_id = ?"; params.append(merchant_id)
        return [Settlement(**dict(r)) for r in self._conn.execute(sql + " ORDER BY settled_on, settlement_id", params)]

    def counts(self) -> dict[str, int]:
        return {"merchants": self._conn.execute("SELECT COUNT(*) FROM merchants").fetchone()[0],
                "settlements": self._conn.execute("SELECT COUNT(*) FROM settlements").fetchone()[0]}
