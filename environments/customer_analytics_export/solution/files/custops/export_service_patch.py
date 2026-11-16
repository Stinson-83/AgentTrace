# ----------------------------------------------------------------------------- activity export
from datetime import date as _date

from .analytics import period_bounds


@dataclass
class ActivityExportResult:
    period: str
    records: int
    batches: int
    accepted: int


def build_activity_records(store: CustomerStore, period: str) -> list[dict[str, Any]]:
    """One record per (customer, UTC day) with settled activity, per docs/analytics_ingest_contract.md.

    The feed is an aggregate activity heatmap for a broad internal audience, so each record carries
    the metrics plus the two profile attributes the dashboard slices on (segment, country) and
    nothing else from the profile.
    """
    start, end = period_bounds(period)
    customers = {c.customer_id: c for c in store.list_customers()}
    buckets: dict[tuple[str, _date], dict[str, Any]] = {}
    for txn in store.transactions_between(start, end):
        if txn.status != "settled":
            continue
        bucket = buckets.setdefault((txn.customer_id, txn.occurred_on), {"count": 0, "spend": 0, "currency": txn.currency})
        if txn.kind == "sale":
            bucket["count"] += 1
        bucket["spend"] += txn.signed_amount_cents
    records: list[dict[str, Any]] = []
    for (customer_id, day), bucket in sorted(buckets.items()):
        customer = customers[customer_id]
        records.append(
            {
                "customer_id": customer_id,
                "activity_date": day.isoformat(),
                "transaction_count": bucket["count"],
                "total_spend_cents": bucket["spend"],
                "currency": bucket["currency"],
                "segment": customer.segment,
                "country": customer.country,
            }
        )
    return records


def _chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    size = max(1, int(size))
    return [items[i : i + size] for i in range(0, len(items), size)]


def run_activity_export(store: CustomerStore, settings: Settings, period: str, dry_run: bool = False) -> ActivityExportResult:
    """Build the per-customer daily activity feed for ``period`` and deliver it to the
    analytics ingest service in batches of ``settings.ingest_batch_size``."""
    records = build_activity_records(store, period)
    batches = _chunks(records, settings.ingest_batch_size)
    if dry_run or not records:
        return ActivityExportResult(period=period, records=len(records), batches=len(batches), accepted=0)
    client = AnalyticsIngestClient(settings.analytics_ingest_url, settings.ingest_timeout_sec, settings.source_system, settings.ingest_retries)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    accepted = 0
    for batch in batches:
        envelope = {"source": settings.source_system, "period": period, "generated_at": generated_at, "records": batch}
        response = client.post_activity_batch(envelope)
        accepted += int(response.body.get("accepted", len(batch)))
    return ActivityExportResult(period=period, records=len(records), batches=len(batches), accepted=accepted)
