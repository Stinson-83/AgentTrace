import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ledgerline.classification import classify, permits
from ledgerline.financial_report import PeriodError, build_partner_feed, push_partner_feed
from ledgerline.integrations import GatewayError, PartnerGatewayClient, PartnerRegistry


class _Capture(BaseHTTPRequestHandler):
    docs = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Capture.docs.append((self.path, body))
        data = json.dumps({"receipt_id": "rc_test", "accepted": len(body["merchants"])}).encode()
        self.send_response(202); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture()
def gateway():
    _Capture.docs = []
    srv = HTTPServer(("127.0.0.1", 0), _Capture)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield PartnerGatewayClient(f"http://127.0.0.1:{srv.server_port}", 2, "corvid-test"), _Capture.docs
    srv.shutdown()


def test_feed_rows_within_clearance(store, settings):
    tally = PartnerRegistry(settings.partners_file).get("tally_insights")
    doc = build_partner_feed(store, settings, tally, "2025-10")
    assert doc["document"] == "settlement-feed/1" and len(doc["merchants"]) == 8
    for row in doc["merchants"]:
        assert set(row) <= set(tally.approved_fields)
        assert all(permits(tally.clearance, classify(f)) for f in row)
    assert doc["merchants"][0]["settlement_reference"].startswith("CPS-")


def test_push_feed(store, settings, gateway):
    client, docs = gateway
    tally = PartnerRegistry(settings.partners_file).get("tally_insights")
    result = push_partner_feed(store, settings, tally, "2025-10", client=client)
    assert result.receipt_id == "rc_test" and result.merchants == result.accepted == 8
    assert docs[0][0] == tally.endpoint and docs[0][1]["period"] == "2025-10"
    empty = push_partner_feed(store, settings, tally, "2024-01", client=client)
    assert empty.merchants == 0 and empty.receipt_id is None and len(docs) == 1


def test_errors(store, settings):
    tally = PartnerRegistry(settings.partners_file).get("tally_insights")
    with pytest.raises(PeriodError):
        push_partner_feed(store, settings, tally, "2025-99")
    with pytest.raises(GatewayError):
        push_partner_feed(store, settings, tally, "2025-10")  # settings gateway url is a closed port
