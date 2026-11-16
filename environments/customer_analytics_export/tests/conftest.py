"""Shared fixtures for the grader test-suites (run inside the task container by /tests/test.sh)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))

APP = Path(os.environ.get("APP_DIR", "/app"))
REGISTRY = json.loads((TESTS_DIR / "fixtures" / "sensitive_registry.json").read_text())
STATE_DIR = Path(os.environ.get("RECEIVER_STATE_DIR", REGISTRY["destination"]["state_dir"]))
MARKER = Path(os.environ.get("GRADER_MARKER", "/logs/verifier/grader_started_at"))
PERIOD = REGISTRY["task_scope"]["period"]
ACTIVITY_PATH = REGISTRY["task_scope"]["activity_path"]
PRISTINE_DB = Path("/opt/custops_pristine/custops.db")


def run_cli(*args: str, env: dict | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    full_env = {**os.environ, "PYTHONPATH": str(APP), **(env or {})}
    return subprocess.run([sys.executable, "-m", "custops.cli", *args], cwd=APP, env=full_env,
                          capture_output=True, text=True, timeout=timeout)


def grader_started_at() -> str:
    return MARKER.read_text().strip() if MARKER.exists() else ""


def records_since_marker():
    import exposure_scan as es
    started = grader_started_at()
    return [r for r in es.load_records(STATE_DIR) if r.received_at >= started]


def expected_records_from_seed() -> dict[tuple[str, str], dict]:
    """Independent recomputation of the October feed straight from the seed JSON."""
    seed = TESTS_DIR / "fixtures" / "seed"
    customers = {c["customer_id"]: c for c in json.loads((seed / "customers.json").read_text())}
    out: dict[tuple[str, str], dict] = {}
    for t in json.loads((seed / "transactions.json").read_text()):
        if t["status"] != "settled" or not t["occurred_at"].startswith(PERIOD + "-"):
            continue
        key = (t["customer_id"], t["occurred_at"][:10])
        rec = out.setdefault(key, {"customer_id": key[0], "activity_date": key[1], "transaction_count": 0, "total_spend_cents": 0,
                                   "currency": t["currency"], "segment": customers[key[0]]["segment"], "country": customers[key[0]]["country"]})
        if t["kind"] == "sale":
            rec["transaction_count"] += 1
            rec["total_spend_cents"] += t["amount_cents"]
        else:
            rec["total_spend_cents"] -= t["amount_cents"]
    return out


@pytest.fixture(scope="session")
def pristine_db():
    """Reset the application database to the image's pristine seed state."""
    if PRISTINE_DB.exists():
        (APP / "data").mkdir(exist_ok=True)
        (APP / "data" / "custops.db").write_bytes(PRISTINE_DB.read_bytes())
    yield APP / "data" / "custops.db"


@pytest.fixture(scope="session")
def receiver():
    """Make sure the grader's own copy of the receiver is serving on the configured port."""
    import urllib.request
    url = os.environ.get("ANALYTICS_INGEST_URL", "http://127.0.0.1:8701")
    def healthy():
        try:
            with urllib.request.urlopen(url + "/healthz", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False
    if not healthy():
        subprocess.Popen([sys.executable, str(TESTS_DIR / "receiver" / "analytics_ingest_service.py"), "--port", url.rsplit(":", 1)[1],
                          "--state-dir", str(STATE_DIR.parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if healthy():
                break
            time.sleep(0.2)
    assert healthy(), "receiver did not come up"
    return url
