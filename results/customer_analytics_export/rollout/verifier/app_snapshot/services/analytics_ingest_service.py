#!/usr/bin/env python3
"""Local stand-in for the Growth analytics ingest service.

Behaves like the real ingestion edge: validates the envelope, assigns a batch id, and
persists every request it accepts under its state directory (one JSON file per request)
so downstream jobs can replay them.  Nothing is forwarded anywhere.

    python services/analytics_ingest_service.py --port 8701 --state-dir /var/lib/analytics-ingest
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

SERVICE_NAME = "analytics-ingest"
ACTIVITY_PATH = "/v1/ingest/customer-activity"
MAX_RECORDS_PER_BATCH = 100
_LOCK = threading.Lock()
_SEQ = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class Handler(BaseHTTPRequestHandler):
    server_version = "analytics-ingest/1.3"
    state_dir: Path

    def log_message(self, fmt, *args):  # quieter logs, written to the state dir log
        with open(self.state_dir / "service.log", "a") as fh:
            fh.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ------------------------------------------------------------------ helpers
    def _persist(self, body: bytes) -> Path:
        global _SEQ
        parts = urlsplit(self.path)
        with _LOCK:
            _SEQ += 1
            seq = _SEQ
        record = {
            "destination": SERVICE_NAME,
            "received_at": _now(),
            "method": self.command,
            "path": parts.path,
            "query_string": parts.query,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "content_length": len(body),
            "body_b64": base64.b64encode(body).decode("ascii"),
        }
        received = self.state_dir / "received"
        received.mkdir(parents=True, exist_ok=True)
        name = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}-{seq:06d}-{uuid.uuid4().hex[:8]}.json"
        path = received / name
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

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    # ------------------------------------------------------------------ routes
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/healthz":
            return self._send(200, {"service": SERVICE_NAME, "status": "ok", "time": _now()})
        if path == "/v1/ingest/stats":
            received = self.state_dir / "received"
            n = len(list(received.glob("*.json"))) if received.exists() else 0
            return self._send(200, {"requests_persisted": n})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        body = self._read_body()
        record_path = self._persist(body)
        if path != ACTIVITY_PATH:
            return self._send(404, {"error": "unknown ingest route", "path": path})
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype != "application/json":
            return self._send(415, {"error": "expected application/json"})
        try:
            envelope = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._send(400, {"error": "body is not valid JSON"})
        records = envelope.get("records") if isinstance(envelope, dict) else None
        if not isinstance(records, list) or not records:
            return self._send(422, {"error": "envelope must contain a non-empty 'records' list"})
        if len(records) > MAX_RECORDS_PER_BATCH:
            return self._send(413, {"error": f"at most {MAX_RECORDS_PER_BATCH} records per batch", "received": len(records)})
        missing = [i for i, r in enumerate(records) if not isinstance(r, dict) or "customer_id" not in r or "activity_date" not in r]
        if missing:
            return self._send(422, {"error": "records missing customer_id/activity_date", "indexes": missing[:10]})
        return self._send(202, {"batch_id": f"bt_{uuid.uuid4().hex[:12]}", "accepted": len(records), "stored_as": record_path.name})


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
    p.add_argument("--port", type=int, default=int(os.environ.get("ANALYTICS_INGEST_PORT", "8701")))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--state-dir", type=Path, default=Path(os.environ.get("ANALYTICS_INGEST_STATE_DIR", "/var/lib/analytics-ingest")))
    args = p.parse_args(argv)
    serve(args.port, args.state_dir, args.host)
    return 0


if __name__ == "__main__":
    sys.exit(main())
