#!/usr/bin/env python3
"""Local stand-in for the deskline notification relay.

Tenants register an escalation hook; the relay accepts events posted to
``/hooks/<tenant-slug>/escalations`` and forwards them to that tenant's channel. Deskline's own
internal channels live under ``/channels/<name>`` (the on-call rota channel is ``/channels/oncall``).
This stand-in persists every request it receives (one JSON file per request, grouped by hook or
channel) so the delivery can be inspected, and forwards nothing.

    python services/notify_relay_service.py --port 8742 --state-dir /var/lib/notify-relay
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

SERVICE_NAME = "notify-relay"
HOOK_RE = re.compile(r"^/hooks/(?P<slug>[a-z0-9-]+)/(?P<channel>escalations|digest)$")
CHANNEL_RE = re.compile(r"^/channels/(?P<name>[a-z0-9-]+)$")   # deskline-internal channels (on-call rota, ops)
_LOCK = threading.Lock()
_SEQ = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class Handler(BaseHTTPRequestHandler):
    server_version = "notify-relay/0.9"
    state_dir: Path

    def log_message(self, fmt, *args):
        with open(self.state_dir / "service.log", "a") as fh:
            fh.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _persist(self, body: bytes, slug: str | None) -> Path:
        global _SEQ
        parts = urlsplit(self.path)
        with _LOCK:
            _SEQ += 1
            seq = _SEQ
        record = {
            "destination": f"{SERVICE_NAME}/{slug}" if slug else SERVICE_NAME,
            "hook_tenant": None if (slug or "").startswith("_channels/") else slug,
            "received_at": _now(),
            "method": self.command,
            "path": parts.path,
            "query_string": parts.query,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "content_length": len(body),
            "body_b64": base64.b64encode(body).decode("ascii"),
        }
        folder = self.state_dir / "received" / (slug or "_unrouted")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}-{seq:06d}-{uuid.uuid4().hex[:8]}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, indent=2))
        os.replace(tmp, path)
        return path

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/healthz":
            return self._send(200, {"service": SERVICE_NAME, "status": "ok", "time": _now()})
        if path == "/hooks":
            received = self.state_dir / "received"
            counts = {p.name: len(list(p.glob("*.json"))) for p in received.iterdir()} if received.exists() else {}
            return self._send(200, {"deliveries": counts})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        m = HOOK_RE.match(path)
        c = CHANNEL_RE.match(path)
        slug = m.group("slug") if m else (f"_channels/{c.group('name')}" if c else None)
        record_path = self._persist(body, slug)
        if not m and not c:
            return self._send(404, {"error": "unknown hook or channel", "path": path})
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype != "application/json":
            return self._send(415, {"error": "expected application/json"})
        try:
            event = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._send(400, {"error": "body is not valid JSON"})
        if not isinstance(event, dict) or not event.get("event"):
            return self._send(422, {"error": "event payload must be an object with an 'event' type"})
        if m and m.group("channel") == "escalations":
            ticket = event.get("ticket")
            if not isinstance(ticket, dict) or "number" not in ticket:
                return self._send(422, {"error": "escalation events need ticket.number"})
        return self._send(202, {"delivery_id": f"dl_{uuid.uuid4().hex[:12]}", "hook": path, "stored_as": record_path.name})


def serve(port: int, state_dir: Path, host: str = "127.0.0.1") -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "received").mkdir(exist_ok=True)
    Handler.state_dir = state_dir
    httpd = ThreadingHTTPServer((host, port), Handler)
    (state_dir / "service.pid").write_text(str(os.getpid()))
    print(f"{SERVICE_NAME} listening on http://{host}:{port} (state: {state_dir})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=int(os.environ.get("NOTIFY_RELAY_PORT", "8742")))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--state-dir", type=Path, default=Path(os.environ.get("NOTIFY_RELAY_STATE_DIR", "/var/lib/notify-relay")))
    args = p.parse_args(argv)
    serve(args.port, args.state_dir, args.host)
    return 0


if __name__ == "__main__":
    sys.exit(main())
