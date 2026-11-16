import json
import threading
from dataclasses import replace
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

import pytest

from ledgerline import cli
from ledgerline.financial_report import PartnerFeedResult, PeriodError, period_bounds, push_partner_feed
from ledgerline.integrations import GatewayError, GatewayResponse, PartnerGatewayClient, PartnerRegistry


@pytest.fixture()
def partner(settings):
    return PartnerRegistry(settings.partners_file).get("tally_insights")


@pytest.fixture()
def client():
    return Mock(spec=PartnerGatewayClient, push=Mock(return_value=GatewayResponse(202, {"receipt_id": "rc_test", "accepted": 3})))


def test_feed_schema_and_paid_totals(store, settings, partner, client):
    paid = [s for s in store.settlements_between(*period_bounds("2025-10")) if s.status == "paid"]
    ids = sorted({s.merchant_id for s in paid})
    client.push.return_value.body["accepted"] = len(ids)
    result = push_partner_feed(store, settings, partner, "2025-10", client)
    assert result == PartnerFeedResult("tally_insights", "2025-10", len(ids), len(ids), "rc_test")
    client.push.assert_called_once()
    destination, doc = client.push.call_args.args
    assert destination == partner
    assert set(doc) == {"document", "entity", "period", "generated_at", "merchants"}
    assert doc["document"] == "settlement-feed/1"
    assert doc["entity"] == settings.reporting_entity
    assert doc["period"] == "2025-10"
    assert datetime.fromisoformat(doc["generated_at"].replace("Z", "+00:00")).utcoffset().total_seconds() == 0
    assert [row["merchant_id"] for row in doc["merchants"]] == ids
    for row in doc["merchants"]:
        merchant = store.merchant(row["merchant_id"])
        settlements = [s for s in paid if s.merchant_id == merchant.merchant_id]
        assert row == {
            "merchant_id": merchant.merchant_id,
            "settlement_reference": merchant.settlement_reference,
            "period": "2025-10",
            "currency": merchant.currency,
            "settlement_count": len(settlements),
            "transaction_count": sum(s.transaction_count for s in settlements),
            "gross_cents": sum(s.gross_cents for s in settlements),
            "fees_cents": sum(s.fees_cents for s in settlements),
            "refunds_cents": sum(s.refunds_cents for s in settlements),
            "net_cents": sum(s.net_cents for s in settlements),
        }
    # Sensitive values must not leak elsewhere in the document either.
    encoded = json.dumps(doc)
    for merchant in store.merchants():
        for name in ("iban", "account_number", "sort_code", "bank_name", "contact_email"):
            assert getattr(merchant, name) not in encoded


@pytest.mark.parametrize("nonpaid_only", [False, True])
def test_empty_feed_does_not_send(store, settings, partner, client, monkeypatch, nonpaid_only):
    if nonpaid_only:
        settlements = store.settlements_between(*period_bounds("2025-10"))
        monkeypatch.setattr(store, "settlements_between", lambda *args: [s for s in settlements if s.status != "paid"])
    else:
        monkeypatch.setattr(store, "settlements_between", lambda *args: [])
    factory = Mock()
    monkeypatch.setattr("ledgerline.financial_report.PartnerGatewayClient", factory)
    for supplied in (client, None):
        assert push_partner_feed(store, settings, partner, "2025-10", supplied) == PartnerFeedResult("tally_insights", "2025-10", 0, 0, None)
    client.push.assert_not_called()
    factory.assert_not_called()


@pytest.mark.parametrize("period", ["", "2025-1", "2025-00", "2025-13", "2025-10-01", "2025-10\n", "0000-01", "9999-12", "２０２５-１０"])
def test_feed_rejects_bad_period_before_sending(store, settings, partner, client, period):
    with pytest.raises(PeriodError):
        push_partner_feed(store, settings, partner, period, client)
    client.push.assert_not_called()


def test_gateway_error_surfaces(store, settings, partner, client):
    failure = GatewayError("unreachable")
    client.push.side_effect = failure
    with pytest.raises(GatewayError) as exc:
        push_partner_feed(store, settings, partner, "2025-10", client)
    assert exc.value is failure


@pytest.mark.parametrize("body,accepted", [({"receipt_id": "rc_test"}, 8), ({"receipt_id": "rc_test", "accepted": 2}, 2)])
def test_gateway_acknowledgement(store, settings, partner, client, body, accepted):
    client.push.return_value = GatewayResponse(202, body)
    assert push_partner_feed(store, settings, partner, "2025-10", client).accepted == accepted


@pytest.mark.parametrize("response", [GatewayResponse(503, {}), GatewayResponse(202, {}), GatewayResponse(202, {"receipt_id": "rc_test", "accepted": -1})])
def test_bad_gateway_response(store, settings, partner, client, response):
    client.push.return_value = response
    with pytest.raises(GatewayError):
        push_partner_feed(store, settings, partner, "2025-10", client)


@pytest.mark.parametrize("changes", [{"clearance": "public"}, {"approved_fields": ["merchant_id"]}])
def test_partner_permissions_checked_before_send(store, settings, partner, client, changes):
    with pytest.raises(GatewayError):
        push_partner_feed(store, settings, replace(partner, **changes), "2025-10", client)
    client.push.assert_not_called()


@pytest.fixture()
def gateway():
    requests = []
    response = {"status": 202}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            doc = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, dict(self.headers), doc))
            data = json.dumps({"receipt_id": "rc_http", "accepted": len(doc["merchants"])}).encode()
            self.send_response(response["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests, response
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_cli_real_gateway_request(store, settings, monkeypatch, capsys, gateway):
    url, requests, response = gateway
    monkeypatch.setattr(cli, "load_settings", lambda: replace(settings, partner_gateway_url=url))
    assert cli.main(["partner-feed", "--partner", "tally_insights", "--period", "2025-10"]) == 0
    output = capsys.readouterr()
    assert not output.err
    for text in ("tally_insights", "2025-10", "merchants=8", "accepted=8", "rc_http"):
        assert text in output.out
    assert len(requests) == 1
    path, headers, doc = requests[0]
    assert path == "/partners/tally-insights/v1/settlement-feeds"
    headers = {name.lower(): value for name, value in headers.items()}
    assert headers["content-type"] == "application/json"
    assert headers["x-partner-id"] == "tally_insights"
    assert headers["x-reporting-entity"] == settings.reporting_entity
    assert doc["document"] == "settlement-feed/1"

    response["status"] = 503
    assert cli.main(["partner-feed", "--partner", "tally_insights", "--period", "2025-10"]) != 0
    assert "503" in capsys.readouterr().err


@pytest.mark.parametrize("partner_id,period,message", [("nobody", "2025-10", "unknown partner"), ("tally_insights", "2025-13", "period must look like")])
def test_cli_invalid_arguments(store, settings, monkeypatch, capsys, partner_id, period, message):
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    push = Mock()
    monkeypatch.setattr("ledgerline.financial_report.PartnerGatewayClient", push)
    assert cli.main(["partner-feed", "--partner", partner_id, "--period", period]) != 0
    assert message in capsys.readouterr().err
    push.assert_not_called()


def test_cli_empty_period(store, settings, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    assert cli.main(["partner-feed", "--partner", "tally_insights", "--period", "2024-01"]) == 0
    output = capsys.readouterr()
    assert "merchants=0 accepted=0" in output.out
    assert "nothing sent" in output.out
    assert not output.err


def test_cli_unreachable_gateway(store, settings, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    # settings fixture points to a closed local port, not the real partner gateway.
    assert cli.main(["partner-feed", "--partner", "tally_insights", "--period", "2025-10"]) != 0
    assert "unreachable" in capsys.readouterr().err


@pytest.mark.parametrize("error", [TimeoutError("timed out"), ConnectionResetError("connection reset")])
def test_gateway_connection_failure_wrapped(settings, partner, monkeypatch, error):
    monkeypatch.setattr("urllib.request.urlopen", Mock(side_effect=error))
    client = PartnerGatewayClient(settings.partner_gateway_url)
    with pytest.raises(GatewayError, match="unreachable"):
        client.push(partner, {"period": "2025-10", "merchants": []})
