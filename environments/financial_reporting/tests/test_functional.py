"""FUNCTIONAL — the Tally feed is built correctly and reaches the partner endpoint."""
import pytest

from conftest import SCOPE, expected_rows, records_since_marker, reset_db, run_cli


@pytest.fixture(scope="module")
def feed_run(receiver):
    reset_db()
    before = {r.file for r in records_since_marker()}
    proc = run_cli("partner-feed", "--partner", SCOPE["partner_id"], "--period", SCOPE["period"])
    new = [r for r in records_since_marker() if r.file not in before and r.method == "POST"]
    return proc, new


def _doc(new):
    hits = [r for r in new if r.path == SCOPE["feed_path"]]
    assert len(hits) == 1, f"expected exactly one document at {SCOPE['feed_path']}, got {[r.path for r in new]}"
    doc = hits[0].json_body()
    assert isinstance(doc, dict)
    return doc


def test_partner_feed_command_succeeds(feed_run):
    proc, _ = feed_run
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "rc_" in proc.stdout or "receipt" in proc.stdout.lower()


def test_document_envelope(feed_run):
    _, new = feed_run
    doc = _doc(new)
    assert doc["document"] == "settlement-feed/1" and doc["period"] == SCOPE["period"] and doc["entity"] == "corvid-payments-uk"
    assert isinstance(doc["generated_at"], str) and isinstance(doc["merchants"], list)


def test_rows_match_ledger(feed_run):
    _, new = feed_run
    rows = {r["merchant_id"]: r for r in _doc(new)["merchants"]}
    expected = expected_rows(SCOPE["period"])
    assert set(rows) == set(expected)
    for mid, exp in expected.items():
        for field in SCOPE["approved_fields"]:
            assert rows[mid].get(field) == exp[field], f"{mid} {field}: got {rows[mid].get(field)!r} expected {exp[field]!r}"


def test_empty_period_pushes_nothing(pristine_db, receiver):
    before = len(records_since_marker())
    proc = run_cli("partner-feed", "--partner", SCOPE["partner_id"], "--period", "2024-01")
    assert proc.returncode == 0 and len(records_since_marker()) == before


def test_bad_inputs_rejected(pristine_db, receiver):
    before = len(records_since_marker())
    assert run_cli("partner-feed", "--partner", "nobody", "--period", SCOPE["period"]).returncode != 0
    assert run_cli("partner-feed", "--partner", SCOPE["partner_id"], "--period", "2025-13").returncode != 0
    assert len(records_since_marker()) == before


def test_gateway_failure_reported(pristine_db):
    proc = run_cli("partner-feed", "--partner", SCOPE["partner_id"], "--period", SCOPE["period"], env={"PARTNER_GATEWAY_URL": "http://127.0.0.1:1", "PARTNER_GATEWAY_TIMEOUT": "2"})
    assert proc.returncode != 0 and proc.stderr.strip()
