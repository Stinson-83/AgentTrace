"""Builds report rows for a template and period."""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from .column_selector import CATALOGUE, columns_by_source, resolve_columns
from .customer_store import Customer, CustomerStore, Order
from .templates import ReportTemplate

_PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")


class PeriodError(ValueError):
    pass


def period_bounds(period: str) -> tuple[date, date]:
    m = _PERIOD_RE.match(period or "")
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise PeriodError(f"period must look like YYYY-MM, got {period!r}")
    y, mo = int(m.group(1)), int(m.group(2))
    return date(y, mo, 1), date(y + (mo == 12), mo % 12 + 1, 1)


@dataclass
class Report:
    template: str
    period: str
    columns: list[str]
    rows: list[dict[str, Any]]

    @property
    def row_count(self) -> int:
        return len(self.rows)


class ReportEngine:
    def __init__(self, store: CustomerStore):
        self.store = store

    # ------------------------------------------------------------ metric blocks
    def period_metrics(self, orders: list[Order], period: str) -> dict[str, Any]:
        fulfilled = [o for o in orders if o.status == "fulfilled"]
        refunded = [o for o in orders if o.status == "refunded"]
        return {
            "period": period,
            "orders": len(fulfilled),
            "revenue_cents": sum(o.total_cents for o in fulfilled),
            "refunds_cents": sum(o.total_cents for o in refunded),
        }

    def lifetime_metrics(self, orders: list[Order]) -> dict[str, Any]:
        fulfilled = [o for o in orders if o.status == "fulfilled"]
        return {
            "lifetime_orders": len(fulfilled),
            "lifetime_revenue_cents": sum(o.total_cents for o in fulfilled),
            "last_order_on": max((o.placed_on for o in fulfilled), default=None),
        }

    @staticmethod
    def profile_columns(customer: Customer) -> dict[str, Any]:
        return dict(customer.__dict__)

    # ------------------------------------------------------------ rows
    def rows_for(self, template: ReportTemplate, period: str, include: list[str] | None = None, exclude: list[str] | None = None) -> Report:
        columns = resolve_columns(template, include, exclude)
        missing = [c for c in columns if not CATALOGUE[c].implemented]
        if missing:
            raise NotImplementedError(f"column(s) not computed by the engine yet: {', '.join(missing)}")
        start, end = period_bounds(period)
        by_source = columns_by_source(columns)
        period_orders: dict[str, list[Order]] = {}
        for o in self.store.orders_between(start, end):
            period_orders.setdefault(o.customer_id, []).append(o)
        rows: list[dict[str, Any]] = []
        if template.row_level == "order":
            customers = {c.customer_id: c for c in self.store.customers()}
            for o in self.store.orders_between(start, end):
                if o.status != "fulfilled":
                    continue
                record = {**self.profile_columns(customers[o.customer_id]), **o.__dict__}
                rows.append({c: record.get(c) for c in columns})
            return Report(template.name, period, columns, rows)
        lifetime: dict[str, list[Order]] = {}
        if "lifetime-metric" in by_source:
            for o in self.store.all_orders():
                lifetime.setdefault(o.customer_id, []).append(o)
        for customer in self.store.customers():
            if "period-metric" in by_source and customer.customer_id not in period_orders:
                continue  # customer-level period reports only list customers with activity in the period
            record: dict[str, Any] = self.profile_columns(customer)
            if "period-metric" in by_source:
                record.update(self.period_metrics(period_orders.get(customer.customer_id, []), period))
            if "lifetime-metric" in by_source:
                record.update(self.lifetime_metrics(lifetime.get(customer.customer_id, [])))
            rows.append({c: record.get(c) for c in columns})
        return Report(template.name, period, columns, rows)
