#!/usr/bin/env python3
"""Local stand-in for ops-observe, the engineering observability service.

Accepts ``POST /v1/events`` as newline-delimited JSON (or a JSON array), validates each event
has an ``event_type``, and persists every request it receives (one JSON file per request) under
its state directory, exactly as received. Nothing is forwarded.

    python services/observability_service.py --port 8790 --state-dir /var/lib/ops-observe
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

SERVICE_NAME = "ops-observe"
_LOCK = threading.Lock()
_SEQ = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_events(body: bytes, content_type: str) -> list:
    text = body.decode("utf-8")
    if "ndjson" in content_type or "jsonl" in content_type:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    doc = json.loads(text)
    return doc if isinstance(doc, list) else [doc]


class Handler(BaseHTTPRequestHandler):
    server_version = "ops-observe/2.1"
    state_dir: Path

    def log_message(self, fmt, *args):
        with open(self.state_dir / "service.log", "a") as fh:
            fh.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _persist(self, body: bytes) -> Path:
        global _SEQ
        parts = urlsplit(self.path)
        with _LOCK:
            _SEQ += 1
            seq = _SEQ
        record = {
            "destination": SERVICE_NAME, "received_at": _now(), "method": self.command, "path": parts.path,
            "query_string": parts.query, "headers": {k.lower(): v for k, v in self.headers.items()},
            "content_length": len(body), "body_b64": base64.b64encode(body).decode("ascii"),
        }
        received = self.state_dir / "received"
        received.mkdir(parents=True, exist_ok=True)
        path = received / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}-{seq:06d}-{uuid.uuid4().hex[:8]}.json"
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
        if path == "/v1/events/stats":
            received = self.state_dir / "received"
            return self._send(200, {"requests_persisted": len(list(received.glob("*.json"))) if received.exists() else 0})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        record_path = self._persist(body)
        if path != "/v1/events":
            return self._send(404, {"error": "unknown route", "path": path})
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype not in ("application/x-ndjson", "application/json", "application/jsonl"):
            return self._send(415, {"error": "expected application/x-ndjson or application/json"})
        try:
            events = parse_events(body, ctype)
        except (ValueError, UnicodeDecodeError) as e:
            return self._send(400, {"error": f"could not parse events: {e}"})
        bad = [i for i, e in enumerate(events) if not isinstance(e, dict) or not e.get("event_type")]
        if not events or bad:
            return self._send(422, {"error": "every event needs an event_type", "indexes": bad[:10]})
        return self._send(202, {"ingested": len(events), "batch_id": f"ob_{uuid.uuid4().hex[:12]}", "stored_as": record_path.name})


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
    p.add_argument("--port", type=int, default=int(os.environ.get("OPS_OBSERVE_PORT", "8790")))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--state-dir", type=Path, default=Path(os.environ.get("OPS_OBSERVE_STATE_DIR", "/var/lib/ops-observe")))
    args = p.parse_args(argv)
    serve(args.port, args.state_dir, args.host)
    return 0


if __name__ == "__main__":
    sys.exit(main())
