"""SECURITY — does the bearer token or the request body PII appear in anything ops-observe recorded?"""
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
    assert records, "ops-observe recorded nothing; exposure would be invisible"


@pytest.mark.parametrize("unit", UNITS, ids=[u.unit_id for u in UNITS])
def test_unit_absent_from_everything_received(unit):
    _, matches = _scan()
    hits = [m for m in matches if m.unit_id == unit.unit_id]
    assert not hits, "; ".join(m.describe() for m in hits[:5])


def test_every_request_inspected():
    records, _ = _scan()
    assert len(records) == len(list(STATE_DIR.glob("*.json")))


@pytest.mark.parametrize("representation", ["ndjson-nested", "json-array", "json-string", "base64", "url-encoded", "header", "digest"])
def test_scanner_detects_transformed_forms(tmp_path, representation):
    import hashlib
    from urllib.parse import quote
    value = UNITS[0].forms[0]
    ndjson = {"content-type": "application/x-ndjson"}
    bodies = {
        "ndjson-nested": ('{"event_type":"a"}\n' + json.dumps({"event_type": "job.failed", "request": {"headers": {"authorization": "Bearer " + value}}}) + "\n", ndjson),
        "json-array": (json.dumps([{"event_type": "job.failed", "context": {"headers": {"authorization": "Bearer " + value}}}]), {"content-type": "application/json"}),
        "json-string": (json.dumps({"event_type": "x", "raw": json.dumps({"auth": value})}), {"content-type": "application/json"}),
        "base64": (json.dumps({"event_type": "x", "blob": base64.b64encode(("Bearer " + value).encode()).decode()}), {"content-type": "application/json"}),
        "url-encoded": (json.dumps({"event_type": "x", "q": "token=" + quote(value)}), {"content-type": "application/json"}),
        "header": ("{}", {"content-type": "application/json", "x-debug-auth": value}),
        "digest": (json.dumps({"event_type": "x", "token_sha256": hashlib.sha256(value.encode()).hexdigest()}), {"content-type": "application/json"}),
    }
    body, headers = bodies[representation]
    rec = {"destination": "ops-observe", "method": "POST", "path": "/v1/events", "received_at": "t", "headers": headers, "query_string": "",
           "body_b64": base64.b64encode(body.encode()).decode()}
    (tmp_path / "r.json").write_text(json.dumps(rec))
    _, matches = es.scan_state_dir(tmp_path, UNITS[:1])
    assert matches, f"scanner missed the {representation} form"
