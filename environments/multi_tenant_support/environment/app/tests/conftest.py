import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deskline.config import Settings  # noqa: E402
from deskline.escalation import TicketService  # noqa: E402
from deskline.tenant_store import TenantStore  # noqa: E402
from deskline.ticket_store import TicketStore, open_connection  # noqa: E402


@pytest.fixture()
def settings(tmp_path):
    return Settings(db_path=tmp_path / "t.db", seed_dir=ROOT / "data" / "seed", relay_url="http://127.0.0.1:1",
                    relay_timeout_sec=1, cache_size=64, sla_hours={"urgent": 4, "high": 8, "normal": 24, "low": 72}, oncall_channel="/channels/oncall")


@pytest.fixture()
def db(settings):
    conn = open_connection(settings.db_path)
    tenants, tickets = TenantStore(conn), TicketStore(conn)
    tenants.load_seed(settings.seed_dir)
    tickets.load_seed(settings.seed_dir)
    yield conn, tenants, tickets
    conn.close()


@pytest.fixture()
def service(db):
    _, tenants, tickets = db
    return TicketService(tickets, tenants)
