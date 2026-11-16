import json

import pytest

from ledgerline.financial_report import PeriodError, period_bounds, summarise_period, write_statement
from ledgerline.integrations import PartnerRegistry


def test_period_bounds():
    assert period_bounds("2025-12")[1].isoformat() == "2026-01-01"
    with pytest.raises(PeriodError):
        period_bounds("2025-13")


def test_summaries_paid_only(store):
    summaries = {s.account.merchant_id: s for s in summarise_period(store, "2025-10")}
    s = summaries["mch_0401"]
    paid = [x for x in store.settlements_between(*period_bounds("2025-10"), merchant_id="mch_0401") if x.status == "paid"]
    assert s.settlement_count == len(paid) and s.gross_cents == sum(x.gross_cents for x in paid) and s.net_cents == sum(x.net_cents for x in paid)
    assert s.to_dict()["iban"].startswith("GB77") and s.to_dict()["period"] == "2025-10"
    assert summarise_period(store, "2024-01") == []


def test_statement_written(store, settings):
    path = write_statement(store, settings, "2025-10")
    doc = json.loads(path.read_text())
    assert doc["document"] == "ledgerline.statement/2" and doc["merchants"] and "iban" in doc["merchants"][0]
    assert doc["totals"]["net_cents"] == sum(m["net_cents"] for m in doc["merchants"])


def test_partner_registry(settings):
    reg = PartnerRegistry(settings.partners_file)
    tally = reg.get("tally_insights")
    assert tally.clearance == "internal" and tally.endpoint.startswith("/partners/tally-insights/")
    assert [p.partner_id for p in reg.all()] == ["northgate_audit", "tally_insights"]
    with pytest.raises(KeyError):
        reg.get("nobody")
