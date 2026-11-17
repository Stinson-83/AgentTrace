#!/usr/bin/env python3
"""Local stand-in for the outbound partner gateway.

In production the gateway signs and forwards documents to each partner's inbound API. This
stand-in validates the envelope, persists every request it receives (one JSON file per request,
grouped by partner path) and forwards nothing.

    python services/partner_gateway_service.py --port 8815 --state-dir /var/lib/partner-gateway
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

SERVICE_NAME = "partner-gateway"
PARTNER_RE = re.compile(r"^/partners/(?P<partner>[a-z0-9-]+)/v1/(?P<doc>[a-z-]+)$")
_LOCK = threading.Lock()
_SEQ = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class Handler(BaseHTTPRequestHandler):
    server_version = "partner-gateway/1.4"
    state_dir: Path

    def log_message(self, fmt, *args):
        with open(self.state_dir / "service.log", "a") as fh:
            fh.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _persist(self, body: bytes, partner: str | None) -> Path:
        global _SEQ
        parts = urlsplit(self.path)
        with _LOCK:
            _SEQ += 1
            seq = _SEQ
        record = {
            "destination": f"{SERVICE_NAME}/{partner}" if partner else SERVICE_NAME, "partner": partner,
            "received_at": _now(), "method": self.command, "path": parts.path, "query_string": parts.query,
            "headers": {k.lower(): v for k, v in self.headers.items()}, "content_length": len(body),
            "body_b64": base64.b64encode(body).decode("ascii"),
        }
        folder = self.state_dir / "received" / (partner or "_unrouted")
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
        if path == "/partners":
            received = self.state_dir / "received"
            return self._send(200, {"deliveries": {p.name: len(list(p.glob("*.json"))) for p in received.iterdir()} if received.exists() else {}})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        m = PARTNER_RE.match(path)
        partner = m.group("partner") if m else None
        record_path = self._persist(body, partner)
        if not m:
            return self._send(404, {"error": "unknown partner route", "path": path})
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype != "application/json":
            return self._send(415, {"error": "expected application/json"})
        try:
            doc = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._send(400, {"error": "body is not valid JSON"})
        if not isinstance(doc, dict) or not doc.get("period") or not isinstance(doc.get("merchants"), list) or not doc["merchants"]:
            return self._send(422, {"error": "document needs a period and a non-empty merchants list"})
        if any(not isinstance(r, dict) or "merchant_id" not in r for r in doc["merchants"]):
            return self._send(422, {"error": "every merchant row needs a merchant_id"})
        return self._send(202, {"receipt_id": f"rc_{uuid.uuid4().hex[:12]}", "partner": partner, "accepted": len(doc["merchants"]), "stored_as": record_path.name})


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
    p.add_argument("--port", type=int, default=int(os.environ.get("PARTNER_GATEWAY_PORT", "8815")))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--state-dir", type=Path, default=Path(os.environ.get("PARTNER_GATEWAY_STATE_DIR", "/var/lib/partner-gateway")))
    args = p.parse_args(argv)
    serve(args.port, args.state_dir, args.host)
    return 0


if __name__ == "__main__":
    sys.exit(main())
