import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reportkit.customer_store import CustomerStore  # noqa: E402
from reportkit.report_engine import ReportEngine  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    s = CustomerStore(tmp_path / "r.db")
    s.load_seed(ROOT / "data" / "seed")
    yield s
    s.close()


@pytest.fixture()
def engine(store):
    return ReportEngine(store)
