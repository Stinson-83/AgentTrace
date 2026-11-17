from datetime import date

import pytest

from ledgerline.classification import classify, highest_class, permits, rank
from ledgerline.store import LedgerError


def test_seed_counts(store):
    assert store.counts()["merchants"] == 8 and store.counts()["settlements"] > 100
    m = store.merchant("mch_0403")
    assert m.currency == "EUR" and m.settlement_reference == "CPS-0403"
    with pytest.raises(LedgerError):
        store.merchant("mch_9999")


def test_settlements_between_half_open(store):
    rows = store.settlements_between(date(2025, 10, 1), date(2025, 11, 1), merchant_id="mch_0401")
    days = {r.settled_on for r in rows}
    assert "2025-10-01" in days and "2025-10-31" in days and "2025-09-30" not in days and "2025-11-01" not in days
    assert all(r.net_cents == r.gross_cents - r.fees_cents - r.refunds_cents for r in rows)


def test_classification_rules():
    assert classify("iban") == "restricted" and classify("net_cents") == "internal" and classify("made_up") == "restricted"
    assert permits("internal", "public") and permits("internal", "internal") and not permits("internal", "restricted")
    assert highest_class(["period", "iban", "net_cents"]) == "restricted" and rank("confidential") == 2
    with pytest.raises(ValueError):
        rank("secret")


def test_programmes_and_enrolment(store):
    assert [m.merchant_id for m in store.merchants(programme="benchmarking")] == ["mch_0401", "mch_0402", "mch_0403", "mch_0405", "mch_0407"]
    m = store.set_programmes("mch_0406", ["benchmarking"])
    assert m.enrolled_in("benchmarking") and store.merchants(programme="benchmarking")[-2].merchant_id == "mch_0406"
    with pytest.raises(LedgerError):
        store.set_programmes("mch_9999", [])
