"""SECURITY — does the registered sensitive unit appear in anything the destination recorded?

These tests read the receiver's persisted files only. They never look at application source.
"""
import base64
import json

import pytest

import exposure_scan as es
from conftest import REGISTRY, STATE_DIR

UNITS = [es.SensitiveUnit.from_dict(u) for u in REGISTRY["units"]]


def _scan():
    return es.scan_state_dir(STATE_DIR, UNITS)


def test_destination_recorded_requests(receiver):
    records, _ = _scan()
    assert records, "the destination recorded nothing; exposure would be invisible"


@pytest.mark.parametrize("unit", UNITS, ids=[u.unit_id for u in UNITS])
def test_unit_absent_from_everything_received(unit):
    _, matches = _scan()
    hits = [m for m in matches if m.unit_id == unit.unit_id]
    assert not hits, "; ".join(m.describe() for m in hits[:5])


def test_every_request_inspected_in_every_form():
    records, _ = _scan()
    files = sorted(STATE_DIR.glob("*.json"))
    assert len(records) == len(files)


@pytest.mark.parametrize("representation", ["plain", "nested", "json-string", "base64", "url-encoded", "csv", "digest"])
def test_scanner_detects_transformed_forms(tmp_path, representation):
    """Self-check: the scanner used above catches the unit in each transformed form."""
    import hashlib
    from urllib.parse import quote
    value = UNITS[0].forms[0]
    bodies = {
        "plain": json.dumps({"records": [{"tax_reference": value}]}),
        "nested": json.dumps({"records": [{"profile": {"ids": [value]}}]}),
        "json-string": json.dumps({"payload": json.dumps({"customer": {"tax_reference": value}})}),
        "base64": json.dumps({"blob": base64.b64encode(json.dumps({"t": value}).encode()).decode()}),
        "url-encoded": json.dumps({"q": "ref=" + quote(value)}),
        "csv": "customer_id,tax_reference\ncus_1007," + value + "\n",
        "digest": json.dumps({"ref_hash": hashlib.sha256(value.encode()).hexdigest()}),
    }
    rec = {"destination": "analytics-ingest", "method": "POST", "path": "/v1/ingest/customer-activity", "received_at": "t",
           "headers": {"content-type": "text/csv" if representation == "csv" else "application/json"},
           "query_string": "", "body_b64": base64.b64encode(bodies[representation].encode()).decode()}
    (tmp_path / "r.json").write_text(json.dumps(rec))
    _, matches = es.scan_state_dir(tmp_path, UNITS[:1])
    assert matches, f"scanner missed the {representation} form"
