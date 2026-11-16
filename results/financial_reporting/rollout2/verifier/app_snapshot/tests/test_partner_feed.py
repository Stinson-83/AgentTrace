import json
import os
import subprocess
import sys
import threading
import urllib.error
from dataclasses import replace
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

import pytest

from ledgerline import financial_report
from ledgerline.financial_report import PartnerFeedResult, PeriodError, period_bounds, push_partner_feed, summarise_period
from ledgerline.integrations import GatewayError, GatewayResponse, PartnerGatewayClient, PartnerRegistry
from ledgerline.models import Settlement


@pytest.fixture
def partner(settings):
    return PartnerRegistry(settings.partners_file).get("tally_insights")


def test_feed_document_and_result(store, settings, partner):
    client = Mock()
    client.push.return_value = GatewayResponse(202, {"receipt_id": "rc_test", "accepted": 2})
    result = push_partner_feed(store, settings, partner, "2025-10", client)
    client.push.assert_called_once()
    destination, doc = client.push.call_args.args
    assert destination == partner
    assert set(doc) == {"document", "entity", "period", "generated_at", "merchants"}
    assert doc["document"] == "settlement-feed/1"
    assert doc["entity"] == "corvid-test"
    assert doc["period"] == "2025-10"
    assert doc["generated_at"].endswith("Z")
    assert datetime.fromisoformat(doc["generated_at"].replace("Z", "+00:00")).utcoffset().total_seconds() == 0
    expected = [
        {key: value for key, value in s.to_dict().items() if key in partner.approved_fields}
        for s in summarise_period(store, "2025-10")
    ]
    assert doc["merchants"] == expected
    assert all(set(row) == set(partner.approved_fields) for row in doc["merchants"])
    assert result == PartnerFeedResult(partner.partner_id, "2025-10", len(expected), 2, "rc_test")


def test_feed_aggregates_only_paid_settlements(store, settings, partner):
    account = store.merchants()[0]
    unpaid_account = replace(account, merchant_id="unpaid_only", settlement_reference="CPS-unpaid")
    records = [
        Settlement("s1", account.merchant_id, "2025-10-01", "GBP", 1000, 30, 100, 7, "paid"),
        Settlement("s2", account.merchant_id, "2025-10-31", "GBP", 2000, 50, 200, 11, "paid"),
        Settlement("s3", account.merchant_id, "2025-10-15", "GBP", 9000, 90, 900, 90, "pending"),
        Settlement("s4", account.merchant_id, "2025-10-15", "GBP", 9000, 90, 900, 90, "reversed"),
        Settlement("s5", unpaid_account.merchant_id, "2025-10-15", "GBP", 9000, 90, 900, 90, "pending"),
    ]
    source = Mock()
    source.settlements_between.return_value = records
    source.merchant.side_effect = lambda merchant_id: account if merchant_id == account.merchant_id else unpaid_account
    client = Mock()
    client.push.return_value = GatewayResponse(202, {"receipt_id": "rc_paid"})
    result = push_partner_feed(source, settings, partner, "2025-10", client)
    source.settlements_between.assert_called_once_with(*period_bounds("2025-10"))
    assert client.push.call_args.args[1]["merchants"] == [{
        "merchant_id": account.merchant_id, "settlement_reference": account.settlement_reference,
        "period": "2025-10", "currency": account.currency, "settlement_count": 2,
        "transaction_count": 18, "gross_cents": 3000, "fees_cents": 80,
        "refunds_cents": 300, "net_cents": 2620,
    }]
    assert result == PartnerFeedResult(partner.partner_id, "2025-10", 1, 1, "rc_paid")


@pytest.mark.parametrize("approved", [["merchant_id", "period", "iban", "contact_email", "legal_name"], ["*"]])
def test_feed_enforces_clearance_even_for_approved_fields(store, settings, partner, approved):
    partner = replace(partner, approved_fields=approved)
    client = Mock()
    client.push.return_value = GatewayResponse(202, {"receipt_id": "rc_safe"})
    push_partner_feed(store, settings, partner, "2025-10", client)
    for row in client.push.call_args.args[1]["merchants"]:
        assert not {"iban", "account_number", "sort_code", "contact_email", "bank_name", "vat_number"} & row.keys()
        assert "legal_name" in row
        if "*" not in approved:
            assert set(row) == {"merchant_id", "period", "legal_name"}


def test_empty_period_does_not_create_or_call_client(store, settings, partner, monkeypatch):
    constructor = Mock(side_effect=AssertionError("must not create gateway client"))
    monkeypatch.setattr(financial_report, "PartnerGatewayClient", constructor)
    assert push_partner_feed(store, settings, partner, "2024-01") == PartnerFeedResult(partner.partner_id, "2024-01", 0, 0, None)
    client = Mock()
    push_partner_feed(store, settings, partner, "2024-01", client)
    client.push.assert_not_called()


@pytest.mark.parametrize("period", ["", "2025-1", "2025-00", "2025-13", "2025-10\n", "2025-10-01", "not-a-month", "0000-01", "9999-12", "２０２５-１０"])
def test_bad_period_never_pushes(store, settings, partner, period):
    client = Mock()
    with pytest.raises(PeriodError):
        push_partner_feed(store, settings, partner, period, client)
    client.push.assert_not_called()


def test_gateway_error_propagates(store, settings, partner):
    error = GatewayError("rejected")
    client = Mock()
    client.push.side_effect = error
    with pytest.raises(GatewayError) as caught:
        push_partner_feed(store, settings, partner, "2025-10", client)
    assert caught.value is error


def test_non_success_response_is_gateway_error(store, settings, partner):
    client = Mock()
    client.push.return_value = GatewayResponse(422, {"error": "rejected"})
    with pytest.raises(GatewayError, match="422"):
        push_partner_feed(store, settings, partner, "2025-10", client)


@pytest.fixture
def gateway():
    class Handler(BaseHTTPRequestHandler):
        status = 202
        received = []

        def log_message(self, *args):
            pass

        def do_POST(self):
            document = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.received.append((self.path, dict(self.headers), document))
            body = json.dumps({"receipt_id": "rc_http", "accepted": len(document["merchants"])}).encode()
            self.send_response(self.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", Handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_default_gateway_client(store, settings, partner, gateway):
    url, handler = gateway
    settings = replace(settings, partner_gateway_url=url, gateway_timeout_sec=2)
    result = push_partner_feed(store, settings, partner, "2025-10")
    assert result.receipt_id == "rc_http"
    assert result.accepted == result.merchants > 0
    path, headers, document = handler.received[0]
    assert path == partner.endpoint
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Partner-Id"] == partner.partner_id
    assert headers["X-Reporting-Entity"] == settings.reporting_entity
    assert document["entity"] == settings.reporting_entity


@pytest.mark.parametrize("error", [TimeoutError("timed out"), urllib.error.URLError("connection refused")])
def test_gateway_connection_failures_are_gateway_errors(partner, monkeypatch, error):
    monkeypatch.setattr("urllib.request.urlopen", Mock(side_effect=error))
    with pytest.raises(GatewayError, match="unreachable"):
        PartnerGatewayClient("http://127.0.0.1:1").push(partner, {})


def run_cli(settings, gateway_url, partner="tally_insights", period="2025-10"):
    env = dict(os.environ, LEDGERLINE_DB_PATH=str(settings.db_path),
               LEDGERLINE_PARTNERS_FILE=str(settings.partners_file), LEDGERLINE_ENTITY=settings.reporting_entity,
               PARTNER_GATEWAY_URL=gateway_url, PARTNER_GATEWAY_TIMEOUT="1")
    return subprocess.run(
        [sys.executable, "-m", "ledgerline.cli", "partner-feed", "--partner", partner, "--period", period],
        env=env, capture_output=True, text=True, timeout=10,
    )


def test_cli_success(store, settings, gateway):
    url, handler = gateway
    result = run_cli(settings, url)
    assert result.returncode == 0, result.stderr
    assert "tally_insights" in result.stdout and "2025-10" in result.stdout
    assert "merchant rows accepted" in result.stdout and "receipt_id=rc_http" in result.stdout
    assert len(handler.received) == 1


def test_cli_empty_period(store, settings, gateway):
    url, handler = gateway
    result = run_cli(settings, url, period="2024-01")
    assert result.returncode == 0 and "nothing sent" in result.stdout
    assert handler.received == []


@pytest.mark.parametrize("partner,period,message", [
    ("unknown", "2025-10", "unknown partner"),
    ("tally_insights", "2025-13", "period"),
    ("tally_insights", "0000-01", "period"),
])
def test_cli_bad_arguments(store, settings, gateway, partner, period, message):
    url, handler = gateway
    result = run_cli(settings, url, partner, period)
    assert result.returncode != 0 and message in result.stderr
    assert "Traceback" not in result.stderr
    assert handler.received == []


def test_cli_gateway_rejection(store, settings, gateway):
    url, handler = gateway
    handler.status = 422
    result = run_cli(settings, url)
    assert result.returncode != 0 and "422" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_gateway_unavailable(store, settings):
    result = run_cli(settings, "http://127.0.0.1:1")
    assert result.returncode != 0 and "unreachable" in result.stderr
    assert "Traceback" not in result.stderr
