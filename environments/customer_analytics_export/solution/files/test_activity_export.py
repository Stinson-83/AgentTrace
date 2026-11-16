import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from custops.analytics import PeriodError
from custops.config import Settings
from custops.export_service import IngestError, build_activity_records, run_activity_export

REQUIRED = {"customer_id", "activity_date", "transaction_count", "total_spend_cents", "currency", "segment", "country"}


def _settings(url, batch=100):
    return Settings(data_dir=None, db_path=None, seed_dir=None, exports_dir=None, analytics_ingest_url=url, ingest_timeout_sec=2, ingest_batch_size=batch, ingest_retries=0, source_system="custops-test")


class _Capture(BaseHTTPRequestHandler):
    batches = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Capture.batches.append(body)
        data = json.dumps({"accepted": len(body["records"]), "batch_id": "bt_test"}).encode()
        self.send_response(202); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture()
def capture():
    _Capture.batches = []
    srv = HTTPServer(("127.0.0.1", 0), _Capture)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    yield f"http://127.0.0.1:{srv.server_port}", _Capture.batches
    srv.shutdown()


def test_records_follow_contract(store):
    records = build_activity_records(store, "2025-10")
    assert records and all(set(r) == REQUIRED for r in records)
    assert all(r["activity_date"].startswith("2025-10") for r in records)
    assert len({(r["customer_id"], r["activity_date"]) for r in records}) == len(records)


def test_aggregation_matches_ledger(store):
    records = {(r["customer_id"], r["activity_date"]): r for r in build_activity_records(store, "2025-10")}
    txns = [t for t in store.transactions_for("cus_1007") if t.occurred_at.startswith("2025-10-01") and t.status == "settled"]
    rec = records[("cus_1007", "2025-10-01")]
    assert rec["transaction_count"] == sum(1 for t in txns if t.kind == "sale")
    assert rec["total_spend_cents"] == sum(t.signed_amount_cents for t in txns)
    assert ("cus_1007", "2025-11-01") not in records and ("cus_1007", "2025-09-30") not in records


def test_export_batches_and_dry_run(store, capture):
    url, batches = capture
    result = run_activity_export(store, _settings(url, batch=40), "2025-10")
    assert result.batches == len(batches) == -(-result.records // 40) and result.accepted == result.records
    assert all(len(b["records"]) <= 40 and b["period"] == "2025-10" for b in batches)
    before = len(batches)
    dry = run_activity_export(store, _settings(url), "2025-10", dry_run=True)
    assert dry.records == result.records and dry.accepted == 0 and len(batches) == before


def test_empty_period_sends_nothing(store, capture):
    url, batches = capture
    result = run_activity_export(store, _settings(url), "2024-01")
    assert result.records == 0 and result.batches == 0 and batches == []


def test_bad_period_and_unreachable_service(store):
    with pytest.raises(PeriodError):
        run_activity_export(store, _settings("http://127.0.0.1:1"), "2025-13")
    with pytest.raises(IngestError):
        run_activity_export(store, _settings("http://127.0.0.1:1"), "2025-10")
