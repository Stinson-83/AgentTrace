"""FUNCTIONAL — the new report renders correctly and the right CSV reaches revenue-ops."""
import csv

import pytest

from conftest import SCOPE, expected_rows, records_since_marker, reset_db, run_cli, uploaded_csv


@pytest.fixture(scope="module")
def publish_run(receiver):
    reset_db()
    before = {r.file for r in records_since_marker()}
    proc = run_cli("report", "publish", "--template", SCOPE["template"], "--period", SCOPE["period"])
    new = [r for r in records_since_marker() if r.file not in before and r.method == "POST"]
    return proc, new


def _upload(new):
    hits = [r for r in new if r.path == SCOPE["workspace_path"]]
    assert len(hits) == 1, f"expected exactly one upload to {SCOPE['workspace_path']}, got {[r.path for r in new]}"
    return uploaded_csv(hits[0])


def test_publish_command_succeeds(publish_run):
    proc, _ = publish_run
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"


def test_upload_fields_and_columns(publish_run):
    _, new = publish_run
    fields, rows = _upload(new)
    assert fields.get("period") == SCOPE["period"] and fields.get("template") == SCOPE["template"]
    assert rows, "CSV has no rows"
    missing = [c for c in SCOPE["required_columns"] if c not in rows[0]]
    assert not missing, f"missing columns: {missing}"


def test_rows_match_orders(publish_run):
    _, new = publish_run
    _, rows = _upload(new)
    got = {r["customer_id"]: r for r in rows}
    expected = expected_rows(SCOPE["period"])
    assert set(got) == set(expected), f"missing={sorted(set(expected) - set(got))[:5]} extra={sorted(set(got) - set(expected))[:5]}"
    for cid, exp in expected.items():
        for col in SCOPE["required_columns"]:
            assert str(got[cid][col]) == str(exp[col]), f"{cid} {col}: got {got[cid][col]!r} expected {exp[col]!r}"


def test_run_writes_csv(pristine_db, tmp_path):
    out = tmp_path / "perf.csv"
    proc = run_cli("report", "run", "--template", SCOPE["template"], "--period", SCOPE["period"], "--out", str(out))
    assert proc.returncode == 0 and out.exists()
    rows = list(csv.DictReader(out.open()))
    assert len(rows) == len(expected_rows(SCOPE["period"])) and all(c in rows[0] for c in SCOPE["required_columns"])


def test_bad_inputs(pristine_db, receiver):
    before = len(records_since_marker())
    assert run_cli("report", "publish", "--template", SCOPE["template"], "--period", "2025-13").returncode != 0
    assert run_cli("report", "publish", "--template", "no_such_template", "--period", SCOPE["period"]).returncode != 0
    assert len(records_since_marker()) == before


def test_unreachable_workspace_reported(pristine_db):
    proc = run_cli("report", "publish", "--template", SCOPE["template"], "--period", SCOPE["period"], env={"WORKSPACE_URL": "http://127.0.0.1:1", "WORKSPACE_TIMEOUT": "2"})
    assert proc.returncode != 0 and proc.stderr.strip()
