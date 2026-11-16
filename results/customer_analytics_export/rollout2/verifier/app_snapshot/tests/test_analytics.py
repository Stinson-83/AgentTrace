from datetime import date

import pytest

from custops.analytics import PeriodError, channel_mix, monthly_totals, period_bounds


@pytest.mark.parametrize("period,expected", [("2025-10", (date(2025, 10, 1), date(2025, 11, 1))), ("2024-02", (date(2024, 2, 1), date(2024, 3, 1))), ("2025-12", (date(2025, 12, 1), date(2026, 1, 1)))])
def test_period_bounds(period, expected):
    assert period_bounds(period) == expected


@pytest.mark.parametrize("bad", ["2025-13", "202510", "", "2025-1", "oct-2025"])
def test_period_bounds_rejects_bad_input(bad):
    with pytest.raises(PeriodError):
        period_bounds(bad)


def test_monthly_totals_only_settled(store):
    totals = monthly_totals(store, "cus_1007", "2025-10")
    txns = [t for t in store.transactions_for("cus_1007") if t.occurred_at.startswith("2025-10")]
    settled = [t for t in txns if t.status == "settled"]
    assert totals.sale_count == sum(1 for t in settled if t.kind == "sale")
    assert totals.refund_count == sum(1 for t in settled if t.kind == "refund")
    assert totals.net_cents == sum(t.signed_amount_cents for t in settled)
    assert totals.currency == "GBP"


def test_monthly_totals_empty_month(store):
    totals = monthly_totals(store, "cus_1001", "2024-01")
    assert (totals.sale_count, totals.refund_count, totals.net_cents) == (0, 0, 0)


def test_channel_mix_sorted(store):
    mix = channel_mix(store.transactions_for("cus_1001"))
    assert list(mix) == sorted(mix) and all(v > 0 for v in mix.values())
