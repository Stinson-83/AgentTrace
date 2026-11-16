from datetime import date

import pytest

from custops.customer_store import CustomerStore, StoreError, Transaction


def test_seed_loads_all_customers(store):
    assert store.count_customers() == 12
    c = store.get_customer("cus_1004")
    assert c.full_name == "Hanna Lindqvist" and c.segment == "enterprise" and c.currency == "EUR"


def test_unknown_customer_raises(store):
    with pytest.raises(StoreError):
        store.get_customer("cus_9999")


def test_list_by_segment(store):
    smb = store.list_customers(segment="smb")
    assert {c.customer_id for c in smb} == {"cus_1002", "cus_1005", "cus_1008", "cus_1010"}


def test_transactions_between_is_half_open(store):
    october = list(store.transactions_between(date(2025, 10, 1), date(2025, 11, 1)))
    ids = {t.txn_id for t in october}
    boundary = [t for t in store.transactions_for("cus_1007") if t.occurred_at in ("2025-09-30T23:59:59Z", "2025-10-01T00:00:00Z", "2025-10-31T23:59:59Z", "2025-11-01T00:00:00Z")]
    by_time = {t.occurred_at: t.txn_id in ids for t in boundary}
    assert by_time == {"2025-09-30T23:59:59Z": False, "2025-10-01T00:00:00Z": True, "2025-10-31T23:59:59Z": True, "2025-11-01T00:00:00Z": False}


def test_add_transactions_roundtrip(tmp_path):
    s = CustomerStore(tmp_path / "x.db")
    s.load_seed(__import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "seed")
    n = s.add_transactions([Transaction("txn_x1", "cus_1001", "2025-10-05T10:00:00Z", "sale", 100, "GBP", "web", "settled")])
    assert n == 1 and any(t.txn_id == "txn_x1" for t in s.transactions_for("cus_1001"))
    assert Transaction("t", "c", "2025-10-05T10:00:00Z", "refund", 50, "GBP", "web", "settled").signed_amount_cents == -50
