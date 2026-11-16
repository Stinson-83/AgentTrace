"""Shared fixtures for the grader suites (run inside the task container by /tests/test.sh)."""
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
SCOPE = REGISTRY["task_scope"]
PRISTINE_DB = Path("/opt/deskline_pristine/deskline.db")
RELAY_URL = os.environ.get("NOTIFY_RELAY_URL", "http://127.0.0.1:8742")


def run_cli(*args: str, env: dict | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    full_env = {**os.environ, "PYTHONPATH": str(APP), **(env or {})}
    return subprocess.run([sys.executable, "-m", "deskline.cli", *args], cwd=APP, env=full_env, capture_output=True, text=True, timeout=timeout)


def grader_started_at() -> str:
    return MARKER.read_text().strip() if MARKER.exists() else ""


def records_since_marker():
    import exposure_scan as es
    started = grader_started_at()
    return [r for r in es.load_records(STATE_DIR) if r.received_at >= started]


def seed(name: str):
    return json.loads((TESTS_DIR / "fixtures" / "seed" / f"{name}.json").read_text())


def reset_db():
    if PRISTINE_DB.exists():
        (APP / "data").mkdir(exist_ok=True)
        (APP / "data" / "deskline.db").write_bytes(PRISTINE_DB.read_bytes())


@pytest.fixture()
def pristine_db():
    reset_db()
    yield APP / "data" / "deskline.db"


@pytest.fixture(scope="session")
def receiver():
    import urllib.request
    def healthy():
        try:
            with urllib.request.urlopen(RELAY_URL + "/healthz", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False
    if not healthy():
        subprocess.Popen([sys.executable, str(TESTS_DIR / "receiver" / "notify_relay_service.py"), "--port", RELAY_URL.rsplit(":", 1)[1],
                          "--state-dir", str(STATE_DIR.parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if healthy():
                break
            time.sleep(0.2)
    assert healthy(), "relay stand-in did not come up"
    return RELAY_URL
