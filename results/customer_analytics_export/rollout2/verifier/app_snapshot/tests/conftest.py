import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custops.customer_store import CustomerStore  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    s = CustomerStore(tmp_path / "test.db")
    s.load_seed(ROOT / "data" / "seed")
    yield s
    s.close()
