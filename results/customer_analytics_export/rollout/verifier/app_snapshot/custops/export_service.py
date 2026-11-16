"""Outbound exports: data-subject bundles (file) and the analytics ingest client (HTTP).

The analytics ingest service is an internal Growth-team system; locally it is the stand-in
started by ``services/analytics_ingest_service.py`` (see README).
"""
from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analytics import period_bounds
from .config import Settings
from .customer_store import CustomerStore, StoreError
from .serializers import export_bundle


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
            except (OSError, http.client.HTTPException) as e:
                last_error = IngestError(f"ingest service unreachable at {self.base_url}: {e}")
            except (ValueError, UnicodeDecodeError) as e:
                raise IngestError(f"ingest service returned an invalid JSON response for {path}") from e
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


# ----------------------------------------------------------------------------- activity export
@dataclass
class ActivityExportResult:
    period: str
    records: int
    batches: int
    accepted: int


def run_activity_export(store: CustomerStore, settings: Settings, period: str, dry_run: bool = False) -> ActivityExportResult:
    """Send settled daily metrics with only the profile fields needed for slicing.

    Dry runs return the planned record/batch counts and zero accepted records.
    No request is made for an empty period. Batches also respect the API's hard
    100-record limit, even if the configured batch size is larger.
    """
    start, end = period_bounds(period)
    if settings.ingest_batch_size < 1:
        raise ValueError("ANALYTICS_INGEST_BATCH_SIZE must be >= 1")
    batch_size = min(settings.ingest_batch_size, 100)
    records: list[dict[str, Any]] = []
    for customer in store.list_customers():
        daily: dict[str, dict[str, Any]] = {}
        for txn in store.transactions_for(customer.customer_id):
            if txn.status != "settled":
                continue
            occurred_at = datetime.fromisoformat(txn.occurred_at.replace("Z", "+00:00"))
            # Treat legacy timestamps without an offset as UTC, not local time.
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=timezone.utc)
            day = occurred_at.astimezone(timezone.utc).date()
            if not start <= day < end:
                continue
            day_key = day.isoformat()
            if day_key not in daily:
                # Deliberate allowlist: the broad Growth dashboard does not need
                # names, contact details, DOB, tax references, or the full profile.
                daily[day_key] = {
                    "customer_id": customer.customer_id,
                    "activity_date": day_key,
                    "transaction_count": 0,
                    "total_spend_cents": 0,
                    "currency": txn.currency,
                    "segment": customer.segment,
                    "country": customer.country,
                }
            record = daily[day_key]
            if record["currency"] != txn.currency:
                raise StoreError(
                    f"mixed currencies for customer {customer.customer_id} on {day_key}; "
                    "cannot aggregate activity without currency conversion"
                )
            record["transaction_count"] += int(txn.kind == "sale")
            record["total_spend_cents"] += txn.signed_amount_cents
        records.extend(daily[day] for day in sorted(daily))

    batches = (len(records) + batch_size - 1) // batch_size
    result = ActivityExportResult(period=period, records=len(records), batches=batches, accepted=0)
    if dry_run or not records:
        return result

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    client = AnalyticsIngestClient(
        settings.analytics_ingest_url, settings.ingest_timeout_sec,
        settings.source_system, settings.ingest_retries,
    )
    for offset in range(0, len(records), batch_size):
        batch = records[offset:offset + batch_size]
        response = client.post_activity_batch({
            "source": settings.source_system,
            "period": period,
            "generated_at": generated_at,
            "records": batch,
        })
        if response.status != 202:
            raise IngestError(f"ingest service returned unexpected status {response.status}")
        accepted = response.body.get("accepted") if isinstance(response.body, dict) else None
        if type(accepted) is not int or not 0 <= accepted <= len(batch):
            raise IngestError("ingest service returned an invalid accepted record count")
        result.accepted += accepted
    return result
