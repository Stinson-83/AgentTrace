"""Activity analytics over the transaction ledger."""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from .customer_store import CustomerStore, Transaction

_PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")


class PeriodError(ValueError):
    pass


def period_bounds(period: str) -> tuple[date, date]:
    """Return (first_day, first_day_of_next_month) for a YYYY-MM period string."""
    m = _PERIOD_RE.match(period or "")
    if not m:
        raise PeriodError(f"period must look like YYYY-MM, got {period!r}")
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        raise PeriodError(f"invalid month in period {period!r}")
    start = date(year, month, 1)
    days = calendar.monthrange(year, month)[1]
    end = date(year + (month == 12), (month % 12) + 1, 1)
    assert (end - start).days == days
    return start, end


def settled(transactions: Iterable[Transaction]) -> list[Transaction]:
    return [t for t in transactions if t.status == "settled"]


@dataclass(frozen=True)
class MonthlyTotals:
    period: str
    sale_count: int
    refund_count: int
    net_cents: int
    currency: str


def monthly_totals(store: CustomerStore, customer_id: str, period: str) -> MonthlyTotals:
    """Net settled position for a single customer over a month (used by ``customer show``)."""
    start, end = period_bounds(period)
    txns = [t for t in store.transactions_for(customer_id) if start <= t.occurred_on < end]
    txns = settled(txns)
    currency = txns[0].currency if txns else store.get_customer(customer_id).currency
    return MonthlyTotals(
        period=period,
        sale_count=sum(1 for t in txns if t.kind == "sale"),
        refund_count=sum(1 for t in txns if t.kind == "refund"),
        net_cents=sum(t.signed_amount_cents for t in txns),
        currency=currency,
    )


def channel_mix(transactions: Iterable[Transaction]) -> dict[str, int]:
    mix: dict[str, int] = {}
    for t in settled(transactions):
        mix[t.channel] = mix.get(t.channel, 0) + 1
    return dict(sorted(mix.items()))
