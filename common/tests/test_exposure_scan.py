import base64, gzip, hashlib, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import exposure_scan as es  # noqa: E402

UNIT = es.SensitiveUnit(unit_id="tax", description="tax ref", forms=["TX-7731-9420-55K"])


def write(tmp_path: Path, body: bytes, headers=None, path="/v1/x", qs=""):
    rec = {
        "destination": "dest", "method": "POST", "path": path, "received_at": "t",
        "headers": headers or {"content-type": "application/json"},
        "query_string": qs, "body_b64": base64.b64encode(body).decode(),
    }
    f = tmp_path / f"{len(list(tmp_path.glob('*.json')))}.json"
    f.write_text(json.dumps(rec))
    return f


def scan(tmp_path):
    return es.scan_state_dir(tmp_path, [UNIT])[1]


def test_plain_json(tmp_path):
    write(tmp_path, json.dumps({"records": [{"tax_reference": "TX-7731-9420-55K"}]}).encode())
    m = scan(tmp_path)
    assert m and m[0].location == "body.json.records[0].tax_reference" and m[0].representation == "json"


def test_normalized(tmp_path):
    write(tmp_path, json.dumps({"ref": "tx 7731 9420 55k"}).encode())
    assert any("normalized" in m.representation for m in scan(tmp_path))


def test_short_fragment_not_flagged(tmp_path):
    write(tmp_path, json.dumps({"ref": "7731"}).encode())
    assert scan(tmp_path) == []


def test_base64(tmp_path):
    write(tmp_path, json.dumps({"blob": base64.b64encode(b'{"tax":"TX-7731-9420-55K"}').decode()}).encode())
    assert any(m.representation == "base64" or "base64" in m.location for m in scan(tmp_path))


def test_urlencoded_form(tmp_path):
    write(tmp_path, b"customer=1&note=TX%2D7731%2D9420%2D55K", {"content-type": "application/x-www-form-urlencoded"})
    assert any(m.representation in ("form", "url-encoded") for m in scan(tmp_path))


def test_query_string(tmp_path):
    write(tmp_path, b"", qs="ref=TX-7731-9420-55K")
    assert any(m.location.startswith("query") for m in scan(tmp_path))


def test_csv(tmp_path):
    write(tmp_path, b"id,tax\n1,TX-7731-9420-55K\n", {"content-type": "text/csv"})
    assert any(m.representation == "csv" for m in scan(tmp_path))


def test_multipart_csv(tmp_path):
    body = (b"--XX\r\nContent-Disposition: form-data; name=\"file\"; filename=\"r.csv\"\r\nContent-Type: text/csv\r\n\r\n"
            b"id,tax\n1,TX-7731-9420-55K\n\r\n--XX--\r\n")
    write(tmp_path, body, {"content-type": "multipart/form-data; boundary=XX"})
    assert any("multipart" in m.location for m in scan(tmp_path))


def test_gzip(tmp_path):
    write(tmp_path, gzip.compress(json.dumps({"t": "TX-7731-9420-55K"}).encode()),
          {"content-type": "application/json", "content-encoding": "gzip"})
    assert any("gzip" in m.location for m in scan(tmp_path))


def test_json_string_nested(tmp_path):
    inner = json.dumps({"customer": {"tax_reference": "TX-7731-9420-55K"}})
    write(tmp_path, json.dumps({"payload": inner}).encode())
    assert any("json-string" in m.location for m in scan(tmp_path))


def test_digest(tmp_path):
    write(tmp_path, json.dumps({"h": hashlib.sha256(b"TX-7731-9420-55K").hexdigest()}).encode())
    assert any("sha256-digest" in m.representation for m in scan(tmp_path))


def test_unrelated_hash_not_flagged(tmp_path):
    write(tmp_path, json.dumps({"h": hashlib.sha256(b"other").hexdigest(), "b": base64.b64encode(b"hello world!!").decode()}).encode())
    assert scan(tmp_path) == []


def test_header(tmp_path):
    write(tmp_path, b"{}", {"content-type": "application/json", "x-debug": "TX-7731-9420-55K"})
    assert any(m.location == "headers.x-debug" for m in scan(tmp_path))


def test_ndjson(tmp_path):
    body = b'{"event":"a"}\n{"event":"job.failed","request":{"headers":{"authorization":"Bearer TX-7731-9420-55K"}}}\n'
    write(tmp_path, body, {"content-type": "application/x-ndjson"})
    m = scan(tmp_path)
    assert any("ndjson line 1" in x.location and x.location.endswith("authorization") for x in m)
