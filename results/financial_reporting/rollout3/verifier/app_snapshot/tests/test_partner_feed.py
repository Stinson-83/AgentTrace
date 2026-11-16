import io
import json
import urllib.error
from dataclasses import replace
from datetime import datetime
from unittest.mock import Mock

import pytest

from ledgerline import cli, financial_report
from ledgerline.classification import classify, permits
from ledgerline.financial_report import (
    MerchantSettlementSummary,
    PartnerFeedResult,
    PeriodError,
    period_bounds,
    push_partner_feed,
    summarise_period,
)
from ledgerline.integrations import GatewayError, GatewayResponse, PartnerGatewayClient, PartnerRegistry


@pytest.fixture()
def partner(settings):
    return PartnerRegistry(settings.partners_file).get("tally_insights")


@pytest.fixture()
def client():
    client = Mock(spec=PartnerGatewayClient)
    client.push.return_value = GatewayResponse(202, {"accepted": 3, "receipt_id": "rc_test"})
    return client


def test_feed_document_and_paid_totals(store, settings, partner, client):
    result = push_partner_feed(store, settings, partner, "2025-10", client=client)
    client.push.assert_called_once()
    destination, doc = client.push.call_args.args
    assert destination == partner
    assert set(doc) == {"document", "entity", "period", "generated_at", "merchants"}
    assert doc["document"] == "settlement-feed/1"
    assert doc["entity"] == settings.reporting_entity
    assert doc["period"] == "2025-10"
    assert doc["generated_at"].endswith("Z")
    assert datetime.fromisoformat(doc["generated_at"].replace("Z", "+00:00")).utcoffset().total_seconds() == 0

    settlements = store.settlements_between(*period_bounds("2025-10"))
    assert {s.status for s in settlements} == {"paid", "pending", "reversed"}
    paid = [s for s in settlements if s.status == "paid"]
    ids = sorted({s.merchant_id for s in paid})
    assert [r["merchant_id"] for r in doc["merchants"]] == ids
    for row in doc["merchants"]:
        merchant = store.merchant(row["merchant_id"])
        batches = [s for s in paid if s.merchant_id == row["merchant_id"]]
        assert row["settlement_reference"] == merchant.settlement_reference
        assert row["currency"] == merchant.currency
        assert row["period"] == "2025-10"
        assert row["settlement_count"] == len(batches)
        for field in ("transaction_count", "gross_cents", "fees_cents", "refunds_cents", "net_cents"):
            assert row[field] == sum(getattr(s, field) for s in batches)
        summary = next(s for s in summarise_period(store, "2025-10") if s.account.merchant_id == row["merchant_id"])
        assert row == {k: v for k, v in summary.to_dict().items() if permits(partner.clearance, classify(k))}
        assert not {"iban", "account_number", "sort_code", "bank_name", "vat_number", "contact_email"} & row.keys()
    assert result == PartnerFeedResult(partner.partner_id, "2025-10", len(ids), 3, "rc_test")


def test_feed_filters_unknown_fields(store, settings, partner, client, monkeypatch):
    original = MerchantSettlementSummary.to_dict
    monkeypatch.setattr(MerchantSettlementSummary, "to_dict", lambda s: {**original(s), "future_private_field": "private"})
    push_partner_feed(store, settings, partner, "2025-10", client)
    assert all("future_private_field" not in row for row in client.push.call_args.args[1]["merchants"])


@pytest.mark.parametrize("clearance", ["internal", "confidential", "restricted"])
def test_feed_obeys_destination_clearance(store, settings, partner, client, clearance):
    partner = replace(partner, clearance=clearance)
    push_partner_feed(store, settings, partner, "2025-10", client)
    rows = client.push.call_args.args[1]["merchants"]
    for row in rows:
        assert all(permits(clearance, classify(field)) for field in row)
    assert ("bank_name" in rows[0]) == permits(clearance, "confidential")
    assert ("iban" in rows[0]) == permits(clearance, "restricted")


def test_feed_uses_configured_client(store, settings, partner, client, monkeypatch):
    factory = Mock(return_value=client)
    monkeypatch.setattr(financial_report, "PartnerGatewayClient", factory)
    push_partner_feed(store, settings, partner, "2025-10")
    factory.assert_called_once_with(settings.partner_gateway_url, settings.gateway_timeout_sec, settings.reporting_entity)
    client.push.assert_called_once()


@pytest.mark.parametrize("injected", [True, False])
def test_empty_feed_does_not_push(store, settings, partner, client, monkeypatch, injected):
    factory = Mock(side_effect=AssertionError("empty period must not construct a gateway client"))
    monkeypatch.setattr(financial_report, "PartnerGatewayClient", factory)
    result = push_partner_feed(store, settings, partner, "2024-01", client if injected else None)
    assert result == PartnerFeedResult(partner.partner_id, "2024-01", 0, 0, None)
    client.push.assert_not_called()
    factory.assert_not_called()


def test_period_with_only_unpaid_settlements_does_not_push(store, settings, partner, client):
    with store._conn:
        store._conn.execute("UPDATE settlements SET status = 'pending' WHERE settled_on >= '2025-10-01' AND settled_on < '2025-11-01'")
    assert push_partner_feed(store, settings, partner, "2025-10", client) == PartnerFeedResult(partner.partner_id, "2025-10", 0, 0, None)
    client.push.assert_not_called()


@pytest.mark.parametrize("period", ["", "2025-1", "2025-00", "2025-13", "2025-10-01", "2025-10\n", "0000-01", "9999-12", "not-a-month"])
def test_feed_invalid_period_does_not_push(store, settings, partner, client, period):
    with pytest.raises(PeriodError):
        push_partner_feed(store, settings, partner, period, client)
    client.push.assert_not_called()


def test_gateway_error_surfaces(store, settings, partner, client):
    error = GatewayError("gateway rejected document")
    client.push.side_effect = error
    with pytest.raises(GatewayError) as exc:
        push_partner_feed(store, settings, partner, "2025-10", client)
    assert exc.value is error


def test_gateway_rejection_status(store, settings, partner, client):
    client.push.return_value = GatewayResponse(422, {"error": "invalid"})
    with pytest.raises(GatewayError, match="422"):
        push_partner_feed(store, settings, partner, "2025-10", client)


def test_gateway_receipt_only_response(store, settings, partner, client):
    client.push.return_value = GatewayResponse(202, {"receipt_id": "rc_receipt_only"})
    result = push_partner_feed(store, settings, partner, "2025-10", client)
    assert result.accepted == result.merchants
    assert result.receipt_id == "rc_receipt_only"


@pytest.fixture()
def cli_gateway(store, settings, monkeypatch):
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    push = Mock(return_value=GatewayResponse(202, {"accepted": 8, "receipt_id": "rc_cli"}))
    monkeypatch.setattr(PartnerGatewayClient, "push", push)
    return push


def test_cli_feed_success(cli_gateway, capsys):
    assert cli.main(["partner-feed", "--partner", "tally_insights", "--period", "2025-10"]) == 0
    output = capsys.readouterr()
    assert "tally_insights" in output.out and "2025-10" in output.out
    assert "8/8" in output.out and "rc_cli" in output.out
    assert output.err == ""
    cli_gateway.assert_called_once()


def test_cli_feed_empty(cli_gateway, capsys):
    assert cli.main(["partner-feed", "--partner", "tally_insights", "--period", "2024-01"]) == 0
    assert "nothing sent" in capsys.readouterr().out
    cli_gateway.assert_not_called()


@pytest.mark.parametrize("partner_id,period,message", [
    ("missing", "2025-10", "unknown partner"),
    ("tally_insights", "2025-13", "period"),
    ("tally_insights", "0000-01", "period"),
])
def test_cli_invalid_input(cli_gateway, capsys, partner_id, period, message):
    assert cli.main(["partner-feed", "--partner", partner_id, "--period", period]) != 0
    output = capsys.readouterr()
    assert message in output.err and output.out == ""
    cli_gateway.assert_not_called()


def test_cli_gateway_failure(cli_gateway, capsys):
    cli_gateway.side_effect = GatewayError("gateway unreachable")
    assert cli.main(["partner-feed", "--partner", "tally_insights", "--period", "2025-10"]) != 0
    output = capsys.readouterr()
    assert "gateway unreachable" in output.err and output.out == ""


@pytest.mark.parametrize("option", ["--partner", "--period"])
def test_cli_required_options(option):
    with pytest.raises(SystemExit) as exc:
        cli.main(["partner-feed", option, "value"])
    assert exc.value.code != 0


def test_gateway_serializes_and_routes_feed(store, settings, partner, monkeypatch):
    response = Mock()
    response.status = 202
    response.read.return_value = b'{"accepted": 8, "receipt_id": "rc_http"}'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    urlopen = Mock(return_value=response)
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = push_partner_feed(store, settings, partner, "2025-10")
    request = urlopen.call_args.args[0]
    assert request.full_url == settings.partner_gateway_url + partner.endpoint
    assert request.get_method() == "POST"
    headers = {k.lower(): v for k, v in request.header_items()}
    assert headers["content-type"] == "application/json"
    assert headers["x-partner-id"] == partner.partner_id
    assert headers["x-reporting-entity"] == settings.reporting_entity
    doc = json.loads(request.data)
    assert doc["document"] == "settlement-feed/1" and len(doc["merchants"]) == 8
    assert all("iban" not in row for row in doc["merchants"])
    assert urlopen.call_args.kwargs["timeout"] == settings.gateway_timeout_sec
    assert result == PartnerFeedResult(partner.partner_id, "2025-10", 8, 8, "rc_http")


@pytest.mark.parametrize("error", [
    urllib.error.URLError("connection refused"),
    TimeoutError("timed out"),
    urllib.error.HTTPError("http://gateway", 422, "rejected", {}, io.BytesIO(b'invalid document')),
])
def test_gateway_transport_failures(store, settings, partner, monkeypatch, error):
    monkeypatch.setattr("urllib.request.urlopen", Mock(side_effect=error))
    with pytest.raises(GatewayError):
        push_partner_feed(store, settings, partner, "2025-10")
