"""Partner integrations: the partner registry (config/partners.json) and the gateway client."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Partner:
    partner_id: str
    name: str
    kind: str                      # e.g. "external-reporting", "bank", "auditor"
    endpoint: str                  # path on the partner gateway
    clearance: str                 # highest data class this partner is cleared to receive
    contact: str = ""
    notes: str = ""


class PartnerRegistry:
    def __init__(self, partners_file: Path):
        raw = json.loads(Path(partners_file).read_text())
        self._partners = {p["partner_id"]: Partner(**p) for p in raw["partners"]}

    def get(self, partner_id: str) -> Partner:
        try:
            return self._partners[partner_id]
        except KeyError:
            raise KeyError(f"unknown partner {partner_id!r}") from None

    def all(self) -> list[Partner]:
        return sorted(self._partners.values(), key=lambda p: p.partner_id)


class GatewayError(RuntimeError):
    pass


@dataclass
class GatewayResponse:
    status: int
    body: dict[str, Any]


class PartnerGatewayClient:
    """JSON client for the outbound partner gateway (locally: services/partner_gateway_service.py)."""

    def __init__(self, base_url: str, timeout_sec: float = 10.0, reporting_entity: str = "corvid-payments-uk"):
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.reporting_entity = reporting_entity

    def push(self, partner: Partner, document: dict[str, Any]) -> GatewayResponse:
        data = json.dumps(document, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + partner.endpoint, data=data, method="POST",
            headers={"Content-Type": "application/json", "X-Reporting-Entity": self.reporting_entity, "X-Partner-Id": partner.partner_id},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
                return GatewayResponse(resp.status, json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raise GatewayError(f"partner gateway returned {e.code} for {partner.partner_id}: {e.read().decode('utf-8', 'replace')}") from e
        except urllib.error.URLError as e:
            raise GatewayError(f"partner gateway unreachable at {self.base_url}: {e.reason}") from e

    def health(self) -> GatewayResponse:
        try:
            with urllib.request.urlopen(self.base_url + "/healthz", timeout=self.timeout_sec) as resp:
                return GatewayResponse(resp.status, json.loads(resp.read().decode("utf-8")))
        except urllib.error.URLError as e:
            raise GatewayError(f"partner gateway unreachable at {self.base_url}: {e.reason}") from e
