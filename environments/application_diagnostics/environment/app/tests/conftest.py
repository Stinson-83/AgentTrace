import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from taskforge.config import Settings  # noqa: E402
from taskforge.job_store import JobStore  # noqa: E402


@pytest.fixture()
def settings(tmp_path):
    return Settings(db_path=tmp_path / "jobs.db", seed_dir=ROOT / "data" / "seed", output_dir=tmp_path / "out",
                    failure_log=tmp_path / "failures.jsonl", observe_url="http://127.0.0.1:1", observe_timeout_sec=1,
                    max_attempts=3, service_name="taskforge-test", environment="test")


@pytest.fixture()
def store(settings):
    s = JobStore(settings.db_path)
    s.load_seed(settings.seed_dir)
    yield s
    s.close()
