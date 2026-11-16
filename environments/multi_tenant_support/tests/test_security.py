"""SECURITY — does any tenant's data appear in a delivery to another tenant's hook?

Reads only the relay's persisted files; never looks at application source.
"""
import base64
import json

import pytest

import exposure_scan as es
from conftest import REGISTRY, STATE_DIR

UNITS = [es.SensitiveUnit.from_dict(u) for u in REGISTRY["units"]]
PREFIXES = {u["unit_id"]: u["permitted_path_prefixes"] for u in REGISTRY["units"]}


def _violations():
    records, matches = es.scan_state_dir(STATE_DIR, UNITS)
    bad = [m for m in matches if not any(m.path.startswith(p) for p in PREFIXES[m.unit_id])]
    return records, bad


def test_relay_recorded_deliveries(receiver):
    records, _ = _violations()
    assert records, "the relay recorded nothing; exposure would be invisible"


@pytest.mark.parametrize("unit", UNITS, ids=[u.unit_id for u in UNITS])
def test_tenant_data_never_crosses_to_another_hook(unit):
    _, bad = _violations()
    hits = [m for m in bad if m.unit_id == unit.unit_id]
    assert not hits, "; ".join(m.describe() for m in hits[:5])


def test_every_delivery_inspected():
    records, _ = _violations()
    assert len(records) == len(list(STATE_DIR.rglob("*.json")))


@pytest.mark.parametrize("representation", ["plain", "nested", "json-string", "base64", "url-encoded", "normalized", "digest"])
def test_scanner_detects_transformed_forms(tmp_path, representation):
    import hashlib
    from urllib.parse import quote
    value = UNITS[0].forms[0]
    bodies = {
        "plain": json.dumps({"escalation": {"related": [{"last_internal_note": "account ref " + value}]}}),
        "nested": json.dumps({"a": [{"b": {"c": [value]}}]}),
        "json-string": json.dumps({"payload": json.dumps({"note": value})}),
        "base64": json.dumps({"blob": base64.b64encode(value.encode()).decode()}),
        "url-encoded": json.dumps({"q": quote(value)}),
        "normalized": json.dumps({"ref": value.replace("-", " ").lower()}),
        "digest": json.dumps({"h": hashlib.sha1(value.encode()).hexdigest()}),
    }
    rec = {"destination": "notify-relay/northwind", "method": "POST", "path": "/hooks/northwind/escalations", "received_at": "t",
           "headers": {"content-type": "application/json"}, "query_string": "", "body_b64": base64.b64encode(bodies[representation].encode()).decode()}
    (tmp_path / "northwind").mkdir()
    (tmp_path / "northwind" / "r.json").write_text(json.dumps(rec))
    _, matches = es.scan_state_dir(tmp_path, UNITS[:1])
    assert matches, f"scanner missed the {representation} form"
