import io
import urllib.error
from dataclasses import replace
from datetime import datetime
from unittest.mock import Mock

import pytest

from ledgerline import cli
from ledgerline.financial_report import PartnerFeedResult, PeriodError, push_partner_feed, summarise_period
from ledgerline.integrations import GatewayError, GatewayResponse, PartnerGatewayClient, PartnerRegistry


FEED_FIELDS = {
    "merchant_id", "settlement_reference", "period", "currency", "settlement_count",
    "transaction_count", "gross_cents", "fees_cents", "refunds_cents", "net_cents",
}


@pytest.fixture()
def partner(settings):
    return PartnerRegistry(settings.partners_file).get("tally_insights")


@pytest.fixture()
def client():
    client = Mock(spec=PartnerGatewayClient)
    client.push.return_value = GatewayResponse(202, {"accepted": 5, "receipt_id": "rc_test"})
    return client


def test_feed_document(store, settings, partner, client):
    result = push_partner_feed(store, settings, partner, "2025-10", client)
    assert result == PartnerFeedResult("tally_insights", "2025-10", 5, 5, "rc_test")
    client.push.assert_called_once()
    sent_partner, doc = client.push.call_args.args
    assert sent_partner == partner
    assert set(doc) == {"document", "entity", "period", "generated_at", "merchants"}
    assert doc["document"] == "settlement-feed/1"
    assert doc["entity"] == settings.reporting_entity
    assert doc["period"] == "2025-10"
    assert datetime.fromisoformat(doc["generated_at"].replace("Z", "+00:00")).utcoffset().total_seconds() == 0
    expected = [s.to_dict() for s in summarise_period(store, "2025-10") if s.account.enrolled_in("benchmarking")]
    assert doc["merchants"] == [{key: row[key] for key in FEED_FIELDS} for row in expected]
    assert len({row["merchant_id"] for row in doc["merchants"]}) == len(expected)
    assert all(set(row) == FEED_FIELDS for row in doc["merchants"])
    assert {row["currency"] for row in doc["merchants"]} == {"GBP", "EUR"}


def test_feed_respects_current_programme_membership(store, settings, partner, client):
    store.set_programmes("mch_0401", [])
    store.set_programmes("mch_0406", ["benchmarking-extra"])
    store.set_programmes("mch_0408", ["instant-payouts", "benchmarking"])
    push_partner_feed(store, settings, partner, "2025-10", client)
    ids = {row["merchant_id"] for row in client.push.call_args.args[1]["merchants"]}
    assert "mch_0401" not in ids and "mch_0406" not in ids and "mch_0408" in ids


def test_feed_without_programme_still_projects_fields(store, settings, partner, client):
    partner = replace(partner, programme=None, clearance="restricted")
    result = push_partner_feed(store, settings, partner, "2025-10", client)
    rows = client.push.call_args.args[1]["merchants"]
    assert result.merchants == len(summarise_period(store, "2025-10")) == 8
    assert all(set(row) == FEED_FIELDS for row in rows)


@pytest.mark.parametrize("empty_kind", ["no_settlements", "no_paid", "no_enrolment"])
def test_empty_feed_does_not_push(store, settings, partner, client, monkeypatch, empty_kind):
    period = "2025-10"
    if empty_kind == "no_settlements":
        period = "2024-01"
    elif empty_kind == "no_paid":
        original = store.settlements_between
        monkeypatch.setattr(store, "settlements_between", lambda *a: [replace(s, status="pending") for s in original(*a)])
    else:
        for merchant in store.merchants():
            store.set_programmes(merchant.merchant_id, [])
    assert push_partner_feed(store, settings, partner, period, client) == PartnerFeedResult(partner.partner_id, period, 0, 0, None)
    client.push.assert_not_called()


@pytest.mark.parametrize("period", ["", "2025-1", "2025-00", "2025-13", "2025-10-01", "2025-10\n", "0000-01", "9999-12"])
def test_invalid_period(store, settings, partner, client, period):
    with pytest.raises(PeriodError):
        push_partner_feed(store, settings, partner, period, client)
    client.push.assert_not_called()


def test_insufficient_clearance_never_pushes(store, settings, partner, client):
    with pytest.raises(GatewayError, match="clearance"):
        push_partner_feed(store, settings, replace(partner, clearance="public"), "2025-10", client)
    client.push.assert_not_called()


def test_gateway_response_counts_and_default_client(store, settings, partner, monkeypatch, client):
    factory = Mock(return_value=client)
    monkeypatch.setattr("ledgerline.financial_report.PartnerGatewayClient", factory)
    client.push.return_value = GatewayResponse(202, {"accepted": 3, "receipt_id": "rc_partial"})
    result = push_partner_feed(store, settings, partner, "2025-10")
    factory.assert_called_once_with(settings.partner_gateway_url, settings.gateway_timeout_sec, settings.reporting_entity)
    assert (result.merchants, result.accepted, result.receipt_id) == (5, 3, "rc_partial")
    # The documented minimal 202 response need only contain the receipt.
    client.push.return_value = GatewayResponse(202, {"receipt_id": "rc_minimal"})
    assert push_partner_feed(store, settings, partner, "2025-10", client).accepted == 5


@pytest.mark.parametrize("error", ["rejected", "unreachable"])
def test_gateway_error_propagates(store, settings, partner, client, error):
    failure = GatewayError(error)
    client.push.side_effect = failure
    with pytest.raises(GatewayError) as exc:
        push_partner_feed(store, settings, partner, "2025-10", client)
    assert exc.value is failure


def test_unexpected_gateway_status(store, settings, partner, client):
    client.push.return_value = GatewayResponse(422, {"error": "rejected"})
    with pytest.raises(GatewayError, match="422"):
        push_partner_feed(store, settings, partner, "2025-10", client)


@pytest.mark.parametrize("error", [
    urllib.error.HTTPError("http://gateway", 422, "rejected", {}, io.BytesIO(b"rejected document")),
    urllib.error.URLError("connection refused"),
    TimeoutError("timed out"),
])
def test_http_client_failure_is_gateway_error(settings, partner, monkeypatch, error):
    monkeypatch.setattr("urllib.request.urlopen", Mock(side_effect=error))
    client = PartnerGatewayClient(settings.partner_gateway_url)
    with pytest.raises(GatewayError):
        client.push(partner, {"period": "2025-10", "merchants": [{"merchant_id": "test"}]})


@pytest.mark.parametrize("case", ["success", "empty", "unknown", "invalid", "gateway"])
def test_cli_outcomes(store, settings, client, monkeypatch, capsys, case):
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr("ledgerline.financial_report.PartnerGatewayClient", Mock(return_value=client))
    partner_id = "nobody" if case == "unknown" else "tally_insights"
    period = {"empty": "2024-01", "invalid": "2025-13"}.get(case, "2025-10")
    if case == "gateway":
        client.push.side_effect = GatewayError("gateway unavailable")
    status = cli.main(["partner-feed", "--partner", partner_id, "--period", period])
    out, err = capsys.readouterr()
    if case in {"success", "empty"}:
        assert status == 0 and not err
        assert f"partner={partner_id}" in out and f"period={period}" in out
        if case == "success":
            assert "merchants=5 accepted=5 receipt_id=rc_test" in out
        else:
            assert "merchants=0 accepted=0 receipt_id=-" in out
    else:
        assert status != 0 and err and not out
    if case in {"empty", "unknown", "invalid"}:
        client.push.assert_not_called()
