import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ledgerline.config import Settings  # noqa: E402
from ledgerline.store import LedgerStore  # noqa: E402


@pytest.fixture()
def settings(tmp_path):
    return Settings(db_path=tmp_path / "l.db", seed_dir=ROOT / "data" / "seed", statements_dir=tmp_path / "statements",
                    partners_file=ROOT / "config" / "partners.json", partner_gateway_url="http://127.0.0.1:1", gateway_timeout_sec=1,
                    reporting_entity="corvid-test")


@pytest.fixture()
def store(settings):
    s = LedgerStore(settings.db_path)
    s.load_seed(settings.seed_dir)
    yield s
    s.close()
