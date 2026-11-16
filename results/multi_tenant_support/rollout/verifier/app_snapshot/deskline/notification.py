"""Outbound notifications to each tenant's escalation channel via the notification relay.

Every tenant configures an escalation hook (``tenants.escalation_hook``, e.g.
``/hooks/northwind/escalations``); the relay forwards whatever is posted there to the
tenant's own channel (Slack / Teams / e-mail digest). Locally the relay is the stand-in in
``services/notify_relay_service.py``.
"""
from __future__ import annotations

import json
from http.client import HTTPException
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
                body = json.loads(raw) if raw else {}
                if not isinstance(body, dict):
                    raise RelayError("invalid relay response: expected a JSON object")
                return RelayResponse(resp.status, body)
        except urllib.error.HTTPError as e:
            raise RelayError(f"relay rejected the notification ({e.code}): {e.read().decode('utf-8', 'replace')}") from e
        except urllib.error.URLError as e:
            raise RelayError(f"relay unreachable at {self.base_url}: {e.reason}") from e
        except (OSError, HTTPException) as e:
            raise RelayError(f"relay unreachable at {self.base_url}: {e}") from e
        except ValueError as e:
            raise RelayError(f"invalid relay response: {e}") from e

    def health(self) -> RelayResponse:
        try:
            with urllib.request.urlopen(self.base_url + "/healthz", timeout=self.timeout_sec) as resp:
                return RelayResponse(resp.status, json.loads(resp.read().decode("utf-8")))
        except urllib.error.URLError as e:
            raise RelayError(f"relay unreachable at {self.base_url}: {e.reason}") from e
