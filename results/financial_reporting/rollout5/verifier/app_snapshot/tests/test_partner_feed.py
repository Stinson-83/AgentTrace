import base64
import json
import threading
from dataclasses import replace
from datetime import datetime
from http.server import ThreadingHTTPServer
from unittest.mock import Mock

import pytest

from ledgerline import cli
from ledgerline.classification import classify, permits
from ledgerline.financial_report import (
    MerchantSettlementSummary, PartnerFeedResult, PeriodError,
    period_bounds, push_partner_feed, summarise_period,
)
from ledgerline.integrations import GatewayError, GatewayResponse, PartnerRegistry
from services.partner_gateway_service import Handler


FEED_FIELDS = {
    "merchant_id", "settlement_reference", "period", "currency",
    "settlement_count", "transaction_count", "gross_cents", "fees_cents",
    "refunds_cents", "net_cents",
}


@pytest.fixture()
def partner(settings):
    return PartnerRegistry(settings.partners_file).get("tally_insights")


@pytest.fixture()
def client():
    c = Mock()
    c.push.return_value = GatewayResponse(202, {"accepted": 3, "receipt_id": "rc_test"})
    return c


def test_feed_schema_paid_totals_and_programme(store, settings, partner, client, monkeypatch):
    # A future field added to the internal summary must not leak onto the wire.
    original = MerchantSettlementSummary.to_dict
    monkeypatch.setattr(MerchantSettlementSummary, "to_dict", lambda s: {**original(s), "future_secret": "private"})
    result = push_partner_feed(store, settings, partner, "2025-10", client)
    client.push.assert_called_once()
    destination, doc = client.push.call_args.args
    assert destination == partner
    assert set(doc) == {"document", "entity", "period", "generated_at", "merchants"}
    assert doc["document"] == "settlement-feed/1"
    assert doc["entity"] == settings.reporting_entity
    assert doc["period"] == "2025-10"
    assert datetime.fromisoformat(doc["generated_at"].replace("Z", "+00:00")).utcoffset().total_seconds() == 0
    summaries = [s for s in summarise_period(store, "2025-10") if s.account.enrolled_in("benchmarking")]
    assert doc["merchants"] == [{k: s.to_dict()[k] for k in FEED_FIELDS} for s in summaries]
    assert len({r["merchant_id"] for r in doc["merchants"]}) == len(summaries)
    assert result == PartnerFeedResult(partner.partner_id, "2025-10", len(summaries), 3, "rc_test")
    for row in doc["merchants"]:
        assert set(row) == FEED_FIELDS
        assert all(permits(partner.clearance, classify(k)) for k in row)
        paid = [s for s in store.settlements_between(*period_bounds("2025-10"), merchant_id=row["merchant_id"]) if s.status == "paid"]
        assert row["settlement_count"] == len(paid)
        for field in ("gross_cents", "fees_cents", "refunds_cents", "net_cents", "transaction_count"):
            assert row[field] == sum(getattr(s, field) for s in paid)


def test_feed_uses_current_enrolment(store, settings, partner, client):
    store.set_programmes("mch_0401", [])
    store.set_programmes("mch_0406", ["benchmarking"])
    push_partner_feed(store, settings, partner, "2025-10", client)
    ids = {r["merchant_id"] for r in client.push.call_args.args[1]["merchants"]}
    assert "mch_0401" not in ids and "mch_0406" in ids


def test_partner_without_programme(store, settings, partner, client):
    partner = replace(partner, programme=None)
    result = push_partner_feed(store, settings, partner, "2025-10", client)
    assert result.merchants == len(summarise_period(store, "2025-10"))
    assert all(set(r) == FEED_FIELDS for r in client.push.call_args.args[1]["merchants"])


@pytest.mark.parametrize("period,programme", [("2024-01", "benchmarking"), ("2025-10", "not-enrolled")])
def test_empty_feed_does_not_push(store, settings, partner, client, period, programme):
    result = push_partner_feed(store, settings, replace(partner, programme=programme), period, client)
    assert result == PartnerFeedResult(partner.partner_id, period, 0, 0, None)
    client.push.assert_not_called()


def test_pending_and_reversed_only_does_not_push(store, settings, partner, client):
    with store._conn:
        store._conn.execute("UPDATE settlements SET status='pending' WHERE status='paid'")
    assert store.counts()["settlements"] > 0
    assert push_partner_feed(store, settings, partner, "2025-10", client).merchants == 0
    client.push.assert_not_called()


@pytest.mark.parametrize("period", ["2025-00", "2025-13", "2025-1", "25-10", "", "2025-10\n", "0000-10", "9999-12", "nonsense"])
def test_feed_invalid_period(store, settings, partner, client, period):
    with pytest.raises(PeriodError):
        push_partner_feed(store, settings, partner, period, client)
    client.push.assert_not_called()


def test_gateway_error_propagates(store, settings, partner, client):
    error = GatewayError("gateway unavailable")
    client.push.side_effect = error
    with pytest.raises(GatewayError) as exc:
        push_partner_feed(store, settings, partner, "2025-10", client)
    assert exc.value is error


def test_rejected_response(store, settings, partner, client):
    client.push.return_value = GatewayResponse(422, {"error": "rejected"})
    with pytest.raises(GatewayError, match="422"):
        push_partner_feed(store, settings, partner, "2025-10", client)


def test_clearance_is_enforced_before_push(store, settings, partner, client):
    with pytest.raises(GatewayError, match="not cleared"):
        push_partner_feed(store, settings, replace(partner, clearance="public"), "2025-10", client)
    client.push.assert_not_called()


@pytest.fixture()
def gateway(tmp_path):
    state = tmp_path / "gateway"
    state.mkdir()
    class TestHandler(Handler):
        state_dir = state
    server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_cli_delivers_through_default_client(store, settings, gateway, monkeypatch, capsys):
    url, state = gateway
    monkeypatch.setattr(cli, "load_settings", lambda: replace(settings, partner_gateway_url=url))
    assert cli.main(["partner-feed", "--partner", "tally_insights", "--period", "2025-10"]) == 0
    out = capsys.readouterr().out
    assert "tally_insights 2025-10" in out and "accepted; receipt_id=rc_" in out
    records = list((state / "received" / "tally-insights").glob("*.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text())
    assert record["path"] == "/partners/tally-insights/v1/settlement-feeds"
    assert record["headers"]["x-reporting-entity"] == settings.reporting_entity
    assert record["headers"]["x-partner-id"] == "tally_insights"
    doc = json.loads(base64.b64decode(record["body_b64"]))
    assert all(set(r) == FEED_FIELDS for r in doc["merchants"])


@pytest.mark.parametrize("partner_id,period,message", [
    ("nobody", "2025-10", "unknown partner"),
    ("tally_insights", "2025-13", "invalid period"),
    ("tally_insights", "bad", "period must look like"),
])
def test_cli_input_errors(store, settings, monkeypatch, capsys, partner_id, period, message):
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    assert cli.main(["partner-feed", "--partner", partner_id, "--period", period]) != 0
    assert message in capsys.readouterr().err


def test_cli_empty_period(store, settings, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    assert cli.main(["partner-feed", "--partner", "tally_insights", "--period", "2024-01"]) == 0
    assert "0 merchants, 0 accepted" in capsys.readouterr().out


def test_cli_gateway_rejection(store, settings, gateway, monkeypatch, capsys):
    url, _ = gateway
    registry = json.loads(settings.partners_file.read_text())
    registry["partners"][0]["endpoint"] = "/invalid-route"
    path = settings.db_path.parent / "partners.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(cli, "load_settings", lambda: replace(settings, partners_file=path, partner_gateway_url=url))
    assert cli.main(["partner-feed", "--partner", "tally_insights", "--period", "2025-10"]) != 0
    assert "gateway returned 404" in capsys.readouterr().err


def test_cli_gateway_unreachable(store, settings, monkeypatch, capsys):
    import urllib.error
    import urllib.request
    def unreachable(*args, **kwargs):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", unreachable)
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    assert cli.main(["partner-feed", "--partner", "tally_insights", "--period", "2025-10"]) != 0
    assert "gateway unreachable" in capsys.readouterr().err


def test_receipt_only_response(store, settings, partner, client):
    client.push.return_value = GatewayResponse(202, {"receipt_id": "rc_only"})
    result = push_partner_feed(store, settings, partner, "2025-10", client)
    assert result.accepted == result.merchants and result.receipt_id == "rc_only"


def test_timeout_becomes_gateway_error(store, settings, partner, monkeypatch):
    import urllib.request
    def timeout(*args, **kwargs):
        raise TimeoutError("timed out")
    monkeypatch.setattr(urllib.request, "urlopen", timeout)
    with pytest.raises(GatewayError, match="timed out"):
        push_partner_feed(store, settings, partner, "2025-10")
