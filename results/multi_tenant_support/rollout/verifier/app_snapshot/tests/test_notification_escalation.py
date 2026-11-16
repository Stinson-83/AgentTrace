import io
import json
import os
import subprocess
import sys
import threading
import urllib.error
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

import pytest

from deskline.escalation import escalate
from deskline.notification import NotificationRelayClient


@pytest.mark.parametrize("status", [202, 422])
def test_module_cli_posts_contract_to_tenant_hook(db, settings, status):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            event = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, self.headers, event))
            body = json.dumps({"delivery_id": "dl_http"} if status == 202 else {"error": "test rejection"}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = dict(os.environ, DESKLINE_DB_PATH=str(settings.db_path),
                   NOTIFY_RELAY_URL=f"http://127.0.0.1:{server.server_port}")
        proc = subprocess.run([sys.executable, "-m", "deskline.cli", "escalate", "--tenant", "northwind",
                               "--ticket", "1042", "--reason", "SLA breached, customer chasing"],
                              env=env, capture_output=True, text=True, timeout=10)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert len(received) == 1
    path, headers, event = received[0]
    assert path == "/hooks/northwind/escalations"
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Deskline-Tenant"] == "northwind"
    assert headers["X-Deskline-Event"] == "ticket.escalated"
    assert event["ticket"]["number"] == 1042 and event["ticket"]["status"] == "escalated"
    assert all(t["tenant"] == "northwind" for t in event["escalation"]["related"])
    assert db[2].get_ticket("ten_nw", 1042).status == "escalated"
    if status == 202:
        assert proc.returncode == 0 and "dl_http" in proc.stdout
        assert not proc.stderr
    else:
        assert proc.returncode != 0 and "delivery failed" in proc.stdout
        assert "422" in proc.stderr and "test rejection" in proc.stderr


@pytest.mark.parametrize("error,expected", [
    (urllib.error.URLError("connection refused"), "unreachable"),
    (TimeoutError("timed out"), "timed out"),
    (ConnectionResetError("connection reset"), "connection reset"),
    (IncompleteRead(b"partial"), "unreachable"),
    (urllib.error.HTTPError("http://relay", 422, "Rejected", {}, io.BytesIO(b'{"error":"invalid"}')), "422"),
])
def test_transport_failure_returns_failed_result(db, service, settings, monkeypatch, error, expected):
    monkeypatch.setattr("urllib.request.urlopen", Mock(side_effect=error))
    client = NotificationRelayClient("http://relay", timeout_sec=0.01)
    result = escalate(service, client, settings, db[1].by_slug("northwind"), 1042, "Investigate")
    assert not result.delivered and expected in result.error
    assert service.view("ten_nw", 1042).ticket.status == "escalated"


@pytest.mark.parametrize("raw", [b"not-json", b"[]", b'{"delivery_id":null}'])
def test_malformed_relay_response_is_failed_delivery(db, service, settings, monkeypatch, raw):
    response = Mock(status=202)
    response.read.return_value = raw
    context = Mock()
    context.__enter__ = Mock(return_value=response)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("urllib.request.urlopen", Mock(return_value=context))
    result = escalate(service, NotificationRelayClient("http://relay"), settings,
                      db[1].by_slug("northwind"), 1042, "Investigate")
    assert not result.delivered and result.error
    assert service.view("ten_nw", 1042).ticket.status == "escalated"
