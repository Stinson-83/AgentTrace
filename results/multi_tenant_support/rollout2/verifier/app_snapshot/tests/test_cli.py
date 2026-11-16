import json

import pytest

from deskline import cli
from deskline.notification import NotificationRelayClient, RelayError, RelayResponse


@pytest.fixture
def cli_setup(db, settings, monkeypatch):
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    calls = []

    def post(self, tenant, event):
        calls.append((tenant, event))
        return RelayResponse(202, {"delivery_id": "dl_cli"})

    monkeypatch.setattr(NotificationRelayClient, "post", post)
    return calls


@pytest.mark.parametrize("actor_args,actor", [([], "cli"), (["--actor", "sam"], "sam")])
def test_cli_escalate_success(cli_setup, capsys, actor_args, actor):
    code = cli.main(["escalate", "--tenant", "northwind", "--ticket", "1042", "--reason", "needs on-call"] + actor_args)
    captured = capsys.readouterr()
    assert code == 0 and captured.err == ""
    result = json.loads(captured.out)
    assert result["delivered"] is True and result["delivery_id"] == "dl_cli"
    assert result["tenant"] == "northwind" and result["status"] == "escalated"
    assert cli_setup[0][1]["actor"] == actor
    assert cli_setup[0][1]["escalation"]["reason"] == "needs on-call"


@pytest.mark.parametrize("tenant,number,status,message", [
    ("nobody", "1042", None, "unknown tenant"),
    ("northwind", "99999", None, "not found"),
    ("northwind", "1055", None, "not found"),
    ("northwind", "1042", "resolved", "resolved"),
    ("northwind", "1042", "closed", "closed"),
])
def test_cli_escalate_validation_failure(cli_setup, db, capsys, tenant, number, status, message):
    if status:
        tickets = db[2]
        tickets.update_status(tickets.get_ticket("ten_nw", 1042).ticket_id, status)
    assert cli.main(["escalate", "--tenant", tenant, "--ticket", number, "--reason", "urgent"]) != 0
    captured = capsys.readouterr()
    assert message in captured.err
    assert "Traceback" not in captured.err
    assert cli_setup == []


def test_cli_delivery_failure(cli_setup, db, capsys, monkeypatch):
    def fail(self, tenant, event):
        raise RelayError("relay unreachable at test URL")

    monkeypatch.setattr(NotificationRelayClient, "post", fail)
    assert cli.main(["escalate", "--tenant", "northwind", "--ticket", "1042", "--reason", "urgent"]) != 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert not result["delivered"] and result["delivery_id"] is None
    assert "unreachable" in result["error"] and "unreachable" in captured.err
    ticket = db[2].get_ticket("ten_nw", 1042)
    assert ticket.status == "escalated"
    assert "urgent" in db[2].notes_for(ticket.ticket_id)[-1].body
