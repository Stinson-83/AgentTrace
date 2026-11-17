"""Outbound notifications via the relay: tenant escalation hooks (``tenants.escalation_hook``, forwarded
to that tenant's own channel) and deskline's internal channels (``/channels/<name>``, e.g. on-call).
Locally the relay is the stand-in in ``services/notify_relay_service.py``."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .tenant_store import Tenant


class RelayError(RuntimeError):
    pass


@dataclass
class RelayResponse:
    status: int
    body: dict[str, Any]


class NotificationRelayClient:
    def __init__(self, base_url: str, timeout_sec: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec

    def post(self, tenant: Tenant, event: dict[str, Any]) -> RelayResponse:
        data = json.dumps(event, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + tenant.escalation_hook, data=data, method="POST",
            headers={"Content-Type": "application/json", "X-Deskline-Tenant": tenant.slug, "X-Deskline-Event": str(event.get("event", ""))},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
                return RelayResponse(resp.status, json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raise RelayError(f"relay rejected the notification ({e.code}): {e.read().decode('utf-8', 'replace')}") from e
        except urllib.error.URLError as e:
            raise RelayError(f"relay unreachable at {self.base_url}: {e.reason}") from e

    def post_channel(self, channel: str, event: dict[str, Any]) -> RelayResponse:
        """Post an event to an internal deskline channel (``/channels/<name>``)."""
        data = json.dumps(event, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(self.base_url + channel, data=data, method="POST",
                                     headers={"Content-Type": "application/json", "X-Deskline-Event": str(event.get("event", ""))})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
                return RelayResponse(resp.status, json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raise RelayError(f"relay rejected the channel post ({e.code}): {e.read().decode('utf-8', 'replace')}") from e
        except urllib.error.URLError as e:
            raise RelayError(f"relay unreachable at {self.base_url}: {e.reason}") from e

    def health(self) -> RelayResponse:
        try:
            with urllib.request.urlopen(self.base_url + "/healthz", timeout=self.timeout_sec) as resp:
                return RelayResponse(resp.status, json.loads(resp.read().decode("utf-8")))
        except urllib.error.URLError as e:
            raise RelayError(f"relay unreachable at {self.base_url}: {e.reason}") from e
