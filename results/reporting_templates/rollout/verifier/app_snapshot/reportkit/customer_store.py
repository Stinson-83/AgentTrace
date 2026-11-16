"""SQLite store for customers and orders."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY, full_name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT, date_of_birth TEXT,
    residential_address TEXT NOT NULL, postcode TEXT NOT NULL, region TEXT NOT NULL, segment TEXT NOT NULL,
    account_manager TEXT NOT NULL, joined_on TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(customer_id), placed_on TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('fulfilled','cancelled','refunded')), subtotal_cents INTEGER NOT NULL,
    discount_cents INTEGER NOT NULL, total_cents INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_customer_day ON orders(customer_id, placed_on);
"""


@dataclass(frozen=True)
class Customer:
    customer_id: str
    full_name: str
    email: str
    phone: str | None
    date_of_birth: str | None
    residential_address: str
    postcode: str
    region: str
    segment: str
    account_manager: str
    joined_on: str


@dataclass(frozen=True)
class Order:
    order_id: str
    customer_id: str
    placed_on: str
    status: str
    subtotal_cents: int
    discount_cents: int
    total_cents: int


class StoreError(LookupError):
    pass


class CustomerStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def load_seed(self, seed_dir: Path, replace: bool = False) -> tuple[int, int]:
        customers = json.loads((seed_dir / "customers.json").read_text())
        orders = json.loads((seed_dir / "orders.json").read_text())
        with self._conn:
            if replace:
                self._conn.execute("DELETE FROM orders")
                self._conn.execute("DELETE FROM customers")
            self._conn.executemany(
                "INSERT OR REPLACE INTO customers VALUES (:customer_id,:full_name,:email,:phone,:date_of_birth,:residential_address,"
                ":postcode,:region,:segment,:account_manager,:joined_on)", customers)
            self._conn.executemany(
                "INSERT OR REPLACE INTO orders VALUES (:order_id,:customer_id,:placed_on,:status,:subtotal_cents,:discount_cents,:total_cents)", orders)
        return len(customers), len(orders)

    def customer(self, customer_id: str) -> Customer:
        row = self._conn.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
        if row is None:
            raise StoreError(f"unknown customer {customer_id!r}")
        return Customer(**dict(row))

    def customers(self, segment: str | None = None) -> list[Customer]:
        sql, params = "SELECT * FROM customers", []
        if segment:
            sql += " WHERE segment = ?"; params.append(segment)
        return [Customer(**dict(r)) for r in self._conn.execute(sql + " ORDER BY customer_id", params)]

    def orders_between(self, start: date, end_exclusive: date) -> list[Order]:
        rows = self._conn.execute("SELECT * FROM orders WHERE placed_on >= ? AND placed_on < ? ORDER BY placed_on, order_id",
                                  (start.isoformat(), end_exclusive.isoformat()))
        return [Order(**dict(r)) for r in rows]

    def all_orders(self) -> list[Order]:
        return [Order(**dict(r)) for r in self._conn.execute("SELECT * FROM orders ORDER BY placed_on, order_id")]

    def counts(self) -> dict[str, int]:
        return {"customers": self._conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
                "orders": self._conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]}
