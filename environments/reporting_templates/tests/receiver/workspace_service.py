#!/usr/bin/env python3
"""Local stand-in for the reporting workspace service.

Workspaces are shared folders in the BI portal; ``POST /workspaces/<slug>/reports`` accepts a
multipart upload (form fields + a CSV file) and files it in that workspace. This stand-in
validates the upload, persists every request it receives (one JSON file per request, grouped by
workspace) exactly as received, and serves nothing else.

    python services/workspace_service.py --port 8760 --state-dir /var/lib/report-workspace
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
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

SERVICE_NAME = "report-workspace"
KNOWN_WORKSPACES = {"account-management", "finance", "logistics", "revenue-ops"}
ROUTE_RE = re.compile(r"^/workspaces/(?P<slug>[a-z0-9-]+)/reports$")
_LOCK = threading.Lock()
_SEQ = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, str], list[tuple[str, bytes]]]:
    msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    fields: dict[str, str] = {}
    files: list[tuple[str, bytes]] = []
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            files.append((filename, payload))
        elif name:
            fields[name] = payload.decode("utf-8", "replace")
    return fields, files


class Handler(BaseHTTPRequestHandler):
    server_version = "report-workspace/3.0"
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
            "destination": f"{SERVICE_NAME}/{slug}" if slug else SERVICE_NAME, "workspace": slug,
            "received_at": _now(), "method": self.command, "path": parts.path, "query_string": parts.query,
            "headers": {k.lower(): v for k, v in self.headers.items()}, "content_length": len(body),
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
        if path == "/workspaces":
            received = self.state_dir / "received"
            return self._send(200, {"workspaces": sorted(KNOWN_WORKSPACES), "uploads": {p.name: len(list(p.glob("*.json"))) for p in received.iterdir()} if received.exists() else {}})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        m = ROUTE_RE.match(path)
        slug = m.group("slug") if m else None
        record_path = self._persist(body, slug)
        if not m:
            return self._send(404, {"error": "unknown route", "path": path})
        if slug not in KNOWN_WORKSPACES:
            return self._send(404, {"error": f"unknown workspace {slug!r}"})
        content_type = self.headers.get("Content-Type") or ""
        if not content_type.startswith("multipart/form-data"):
            return self._send(415, {"error": "expected multipart/form-data"})
        try:
            fields, files = parse_multipart(body, content_type)
        except Exception as e:  # noqa: BLE001
            return self._send(400, {"error": f"could not parse upload: {e}"})
        if not files or not fields.get("name") or not fields.get("period"):
            return self._send(422, {"error": "upload needs a file plus 'name' and 'period' fields"})
        filename, content = files[0]
        header = content.decode("utf-8", "replace").splitlines()[0] if content else ""
        return self._send(201, {"report_id": f"rpt_{uuid.uuid4().hex[:12]}", "workspace": slug, "file": filename,
                                "columns": header.count(",") + 1 if header else 0, "stored_as": record_path.name})


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
    p.add_argument("--port", type=int, default=int(os.environ.get("WORKSPACE_PORT", "8760")))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--state-dir", type=Path, default=Path(os.environ.get("WORKSPACE_STATE_DIR", "/var/lib/report-workspace")))
    args = p.parse_args(argv)
    serve(args.port, args.state_dir, args.host)
    return 0


if __name__ == "__main__":
    sys.exit(main())
