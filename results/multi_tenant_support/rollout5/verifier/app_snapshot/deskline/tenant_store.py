"""Tenants (customer organisations) and their end-customers."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id     TEXT PRIMARY KEY,
    slug          TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    plan          TEXT NOT NULL,
    timezone      TEXT NOT NULL,
    escalation_hook TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customers (
    customer_id   TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenants(tenant_id),
    name          TEXT NOT NULL,
    email         TEXT NOT NULL,
    account_ref   TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_customers_tenant ON customers(tenant_id);
"""


@dataclass(frozen=True)
class Tenant:
    tenant_id: str
    slug: str
    name: str
    plan: str
    timezone: str
    escalation_hook: str
    created_at: str


@dataclass(frozen=True)
class Customer:
    customer_id: str
    tenant_id: str
    name: str
    email: str
    account_ref: str
    created_at: str


class TenantError(LookupError):
    pass


class TenantStore:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._conn.executescript(SCHEMA)

    def load_seed(self, seed_dir: Path) -> tuple[int, int]:
        tenants = json.loads((seed_dir / "tenants.json").read_text())
        customers = json.loads((seed_dir / "customers.json").read_text())
        with self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO tenants VALUES (:tenant_id,:slug,:name,:plan,:timezone,:escalation_hook,:created_at)", tenants)
            self._conn.executemany(
                "INSERT OR REPLACE INTO customers VALUES (:customer_id,:tenant_id,:name,:email,:account_ref,:created_at)", customers)
        return len(tenants), len(customers)

    def by_slug(self, slug: str) -> Tenant:
        row = self._conn.execute("SELECT * FROM tenants WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise TenantError(f"unknown tenant {slug!r}")
        return Tenant(**dict(row))

    def by_id(self, tenant_id: str) -> Tenant:
        row = self._conn.execute("SELECT * FROM tenants WHERE tenant_id = ?", (tenant_id,)).fetchone()
        if row is None:
            raise TenantError(f"unknown tenant id {tenant_id!r}")
        return Tenant(**dict(row))

    def list_tenants(self) -> list[Tenant]:
        return [Tenant(**dict(r)) for r in self._conn.execute("SELECT * FROM tenants ORDER BY slug")]

    def customer(self, customer_id: str) -> Customer:
        row = self._conn.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
        if row is None:
            raise TenantError(f"unknown customer {customer_id!r}")
        return Customer(**dict(row))
