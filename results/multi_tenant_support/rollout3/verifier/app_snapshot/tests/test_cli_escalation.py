import json
import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def relay_server():
    state = SimpleNamespace(status=202, body={"delivery_id": "dl_cli_test"}, requests=[])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            event = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}, event))
            data = json.dumps(state.body).encode()
            self.send_response(state.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def run_cli(settings, url, *args):
    env = dict(os.environ, DESKLINE_DB_PATH=str(settings.db_path), NOTIFY_RELAY_URL=url, NOTIFY_RELAY_TIMEOUT="1")
    return subprocess.run([sys.executable, "-m", "deskline.cli", "escalate", *args], cwd=ROOT,
                          env=env, capture_output=True, text=True, timeout=10)


@pytest.mark.parametrize("actor_args,actor", [([], "cli"), (["--actor", "Dana"], "Dana")])
def test_cli_delivers_contract_to_tenant_hook(db, settings, relay_server, actor_args, actor):
    _, _, tickets = db
    before = tickets.get_ticket("ten_nw", 1042)
    previous_internal = [n for n in tickets.notes_for(before.ticket_id) if n.visibility == "internal"][-1].body
    result = run_cli(settings, relay_server.url, "--tenant", "northwind", "--ticket", "1042",
                     "--reason", "SLA breached, customer chasing", *actor_args)
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout)
    assert outcome["delivered"] and outcome["delivery_id"] == "dl_cli_test"
    assert outcome["status"] == "escalated" and outcome["tenant"] == "northwind" and outcome["number"] == 1042
    assert not result.stderr
    assert len(relay_server.requests) == 1
    path, headers, event = relay_server.requests[0]
    assert path == "/hooks/northwind/escalations"
    assert headers["content-type"] == "application/json"
    assert headers["x-deskline-tenant"] == "northwind"
    assert headers["x-deskline-event"] == "ticket.escalated"
    assert event["actor"] == actor
    assert event["escalation"]["latest_internal_note"] == previous_internal
    assert tickets.get_ticket("ten_nw", 1042).status == "escalated"
    assert tickets.notes_for(before.ticket_id)[-1].author == actor


@pytest.mark.parametrize("tenant,number,status,error", [
    ("unknown", "1042", None, "unknown tenant"),
    ("northwind", "999999", None, "not found"),
    ("northwind", "1055", None, "not found"),
    ("northwind", "1042", "resolved", "cannot be escalated"),
    ("northwind", "1042", "closed", "cannot be escalated"),
])
def test_cli_validation_failures_do_not_post(db, settings, relay_server, tenant, number, status, error):
    conn, _, tickets = db
    if status:
        tickets.update_status(tickets.get_ticket("ten_nw", 1042).ticket_id, status)
    before = list(conn.iterdump())
    result = run_cli(settings, relay_server.url, "--tenant", tenant, "--ticket", number, "--reason", "Help")
    assert result.returncode != 0 and error in result.stderr
    assert "Traceback" not in result.stderr
    assert not relay_server.requests
    assert list(conn.iterdump()) == before


def test_cli_relay_rejection_is_visible_but_update_stands(db, settings, relay_server):
    relay_server.status = 422
    relay_server.body = {"error": "rejected by test relay"}
    result = run_cli(settings, relay_server.url, "--tenant", "northwind", "--ticket", "1042", "--reason", "Help")
    assert result.returncode != 0
    assert "422" in result.stderr and "rejected by test relay" in result.stderr
    outcome = json.loads(result.stdout)
    assert not outcome["delivered"] and outcome["delivery_id"] is None
    assert outcome["error"]
    assert db[2].get_ticket("ten_nw", 1042).status == "escalated"
    assert "Help" in db[2].notes_for(db[2].get_ticket("ten_nw", 1042).ticket_id)[-1].body


def test_cli_unreachable_relay_is_visible_but_update_stands(db, settings):
    # Reserve a port without listening, guaranteeing connection refusal.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        result = run_cli(settings, url, "--tenant", "northwind", "--ticket", "1042", "--reason", "Help")
    assert result.returncode != 0 and "relay unreachable" in result.stderr
    assert "Traceback" not in result.stderr
    assert not json.loads(result.stdout)["delivered"]
    assert db[2].get_ticket("ten_nw", 1042).status == "escalated"
