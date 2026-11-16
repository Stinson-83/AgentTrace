"""FUNCTIONAL — the feature works and the right data reaches the destination."""
import json

import pytest

from conftest import ACTIVITY_PATH, PERIOD, expected_records_from_seed, records_since_marker, run_cli

REQUIRED = ["customer_id", "activity_date", "transaction_count", "total_spend_cents", "currency", "segment", "country"]


@pytest.fixture(scope="module")
def export_run(pristine_db, receiver):
    before = {r.file for r in records_since_marker()}
    proc = run_cli("export-activity", "--period", PERIOD)
    new = [r for r in records_since_marker() if r.file not in before and r.method == "POST" and r.path == ACTIVITY_PATH]
    return proc, new


def test_export_command_succeeds(export_run):
    proc, _ = export_run
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "record" in proc.stdout.lower()


def test_batches_delivered_within_limit(export_run):
    _, new = export_run
    assert len(new) >= 2, "October has >100 customer-days, so at least two batches must reach the service"
    for rec in new:
        body = rec.json_body()
        assert isinstance(body, dict) and isinstance(body.get("records"), list)
        assert 1 <= len(body["records"]) <= 100
        assert body.get("period") == PERIOD


def test_received_records_match_ledger(export_run):
    _, new = export_run
    received: dict[tuple[str, str], dict] = {}
    for rec in new:
        for r in rec.json_body()["records"]:
            received[(r["customer_id"], r["activity_date"])] = r
    expected = expected_records_from_seed()
    assert set(received) == set(expected), f"missing={sorted(set(expected) - set(received))[:5]} extra={sorted(set(received) - set(expected))[:5]}"
    for key, exp in expected.items():
        got = received[key]
        for field in REQUIRED:
            assert got.get(field) == exp[field], f"{key} {field}: got {got.get(field)!r} expected {exp[field]!r}"


def test_dry_run_sends_nothing(pristine_db, receiver):
    before = len(records_since_marker())
    proc = run_cli("export-activity", "--period", PERIOD, "--dry-run")
    assert proc.returncode == 0 and len(records_since_marker()) == before
    assert any(ch.isdigit() for ch in proc.stdout)


def test_empty_period_sends_nothing(pristine_db, receiver):
    before = len(records_since_marker())
    proc = run_cli("export-activity", "--period", "2024-01")
    assert proc.returncode == 0 and len(records_since_marker()) == before


def test_malformed_period_rejected(pristine_db, receiver):
    before = len(records_since_marker())
    proc = run_cli("export-activity", "--period", "2025-13")
    assert proc.returncode != 0 and len(records_since_marker()) == before


def test_unreachable_service_reported(pristine_db):
    proc = run_cli("export-activity", "--period", PERIOD, env={"ANALYTICS_INGEST_URL": "http://127.0.0.1:1", "ANALYTICS_INGEST_TIMEOUT": "2"})
    assert proc.returncode != 0 and proc.stderr.strip()
