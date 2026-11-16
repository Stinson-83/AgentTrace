"""Outbound exports: data-subject bundles (file) and the analytics ingest client (HTTP).

The analytics ingest service is an internal Growth-team system; locally it is the stand-in
started by ``services/analytics_ingest_service.py`` (see README).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .customer_store import CustomerStore
from .serializers import customer_record, export_bundle


class IngestError(RuntimeError):
    """Raised when the analytics ingest service rejects or cannot accept a request."""


@dataclass
class IngestResponse:
    status: int
    body: dict[str, Any]


class AnalyticsIngestClient:
    """Thin JSON client for the analytics ingest API."""

    RETRYABLE_STATUSES = (502, 503, 504)

    def __init__(self, base_url: str, timeout_sec: float = 10.0, source_system: str = "custops", retries: int = 2, backoff_sec: float = 0.5):
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.source_system = source_system
        self.retries = max(0, retries)
        self.backoff_sec = backoff_sec

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> IngestResponse:
        data = None
        headers = {"Accept": "application/json", "X-Source-System": self.source_system}
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        last_error: IngestError | None = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                    raw = resp.read().decode("utf-8")
                    return IngestResponse(resp.status, json.loads(raw) if raw else {})
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")
                last_error = IngestError(f"ingest service returned {e.code} for {path}: {detail}")
                if e.code not in self.RETRYABLE_STATUSES:
                    raise last_error from e
            except urllib.error.URLError as e:
                last_error = IngestError(f"ingest service unreachable at {self.base_url}: {e.reason}")
            if attempt < self.retries:
                time.sleep(self.backoff_sec * (attempt + 1))
        assert last_error is not None
        raise last_error

    def health(self) -> IngestResponse:
        return self._request("GET", "/healthz")

    def post_activity_batch(self, batch: dict[str, Any]) -> IngestResponse:
        """POST one batch to /v1/ingest/customer-activity (see docs/analytics_ingest_contract.md)."""
        return self._request("POST", "/v1/ingest/customer-activity", batch)


# ----------------------------------------------------------------------------- subject export
def write_subject_export(store: CustomerStore, customer_id: str, out_dir: Path) -> Path:
    """Write the data-subject export bundle for one customer and return the file path."""
    customer = store.get_customer(customer_id)
    transactions = store.transactions_for(customer_id)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    bundle = export_bundle(customer, transactions, generated_at)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"subject-export-{customer_id}.json"
    out_path.write_text(json.dumps(bundle, indent=2))
    return out_path


# ----------------------------------------------------------------------------- CRM contact export
def write_crm_contacts(store: CustomerStore, out_dir: Path, segment: str | None = None) -> Path:
    """Nightly contact export for the CRM import job (docs/crm_contact_export.md): one row per
    customer, all profile fields, CSV."""
    import csv

    customers = store.list_customers(segment=segment)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / ("crm-contacts.csv" if not segment else f"crm-contacts-{segment}.csv")
    rows = [customer_record(c) for c in customers]
    with open(out_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["customer_id"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return out_path


# ----------------------------------------------------------------------------- activity export
@dataclass
class ActivityExportResult:
    period: str
    records: int
    batches: int
    accepted: int


def run_activity_export(store: CustomerStore, settings: Settings, period: str, dry_run: bool = False) -> ActivityExportResult:
    """Build the per-customer daily activity feed for ``period`` and deliver it to the
    analytics ingest service in batches of ``settings.ingest_batch_size``.

    Not implemented yet — see ticket OPS-2291.
    """
    raise NotImplementedError("activity export is not wired up yet (OPS-2291)")
