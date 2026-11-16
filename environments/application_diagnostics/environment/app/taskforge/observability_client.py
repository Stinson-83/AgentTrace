"""HTTP client for the engineering observability service (ops-observe)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class ObserveError(RuntimeError):
    pass


@dataclass
class ObserveResponse:
    status: int
    body: dict[str, Any]


class ObservabilityClient:
    """Sends newline-delimited JSON events to ``POST /v1/events``."""

    def __init__(self, base_url: str, timeout_sec: float = 10.0, service_name: str = "taskforge"):
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.service_name = service_name

    def post_events(self, events: list[dict[str, Any]]) -> ObserveResponse:
        if not events:
            raise ObserveError("no events to send")
        body = "\n".join(json.dumps(e, separators=(",", ":")) for e in events) + "\n"
        req = urllib.request.Request(
            self.base_url + "/v1/events", data=body.encode("utf-8"), method="POST",
            headers={"Content-Type": "application/x-ndjson", "X-Service": self.service_name, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
                return ObserveResponse(resp.status, json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raise ObserveError(f"ops-observe rejected events ({e.code}): {e.read().decode('utf-8', 'replace')}") from e
        except urllib.error.URLError as e:
            raise ObserveError(f"ops-observe unreachable at {self.base_url}: {e.reason}") from e

    def health(self) -> ObserveResponse:
        try:
            with urllib.request.urlopen(self.base_url + "/healthz", timeout=self.timeout_sec) as resp:
                return ObserveResponse(resp.status, json.loads(resp.read().decode("utf-8")))
        except urllib.error.URLError as e:
            raise ObserveError(f"ops-observe unreachable at {self.base_url}: {e.reason}") from e
