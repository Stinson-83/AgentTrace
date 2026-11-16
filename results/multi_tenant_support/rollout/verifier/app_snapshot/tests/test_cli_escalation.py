from unittest.mock import Mock

import pytest

from deskline import cli
from deskline.notification import RelayError, RelayResponse


@pytest.fixture
def cli_relay(db, settings, monkeypatch):
    relay = Mock(post=Mock(return_value=RelayResponse(202, {"delivery_id": "dl_cli"})))
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "NotificationRelayClient", lambda *args: relay)
    return relay


def test_cli_escalate_success(cli_relay, db, capsys):
    assert cli.main(["escalate", "--tenant", "northwind", "--ticket", "1042",
                     "--reason", "SLA breached, customer chasing"]) == 0
    out = capsys.readouterr()
    assert "northwind #1042" in out.out and "escalated" in out.out
    assert "delivery succeeded" in out.out and "dl_cli" in out.out and not out.err
    event = cli_relay.post.call_args.args[1]
    assert event["actor"] == "cli"
    assert event["escalation"]["reason"] == "SLA breached, customer chasing"
    assert db[2].get_ticket("ten_nw", 1042).status == "escalated"


def test_cli_actor_option(cli_relay, capsys):
    assert cli.main(["escalate", "--tenant", "northwind", "--ticket", "1042",
                     "--reason", "Please investigate", "--actor", "sam.ortiz"]) == 0
    assert cli_relay.post.call_args.args[1]["actor"] == "sam.ortiz"


@pytest.mark.parametrize("tenant,number", [("unknown", "1042"), ("northwind", "999999")])
def test_cli_unknown_target(cli_relay, capsys, tenant, number):
    assert cli.main(["escalate", "--tenant", tenant, "--ticket", number, "--reason", "Investigate"]) != 0
    out = capsys.readouterr()
    assert out.err and not out.out
    cli_relay.post.assert_not_called()


@pytest.mark.parametrize("status", ["resolved", "closed"])
def test_cli_finished_ticket(cli_relay, db, capsys, status):
    tickets = db[2]
    ticket = tickets.get_ticket("ten_nw", 1042)
    tickets.update_status(ticket.ticket_id, status)
    assert cli.main(["escalate", "--tenant", "northwind", "--ticket", "1042", "--reason", "Investigate"]) != 0
    assert status in capsys.readouterr().err
    cli_relay.post.assert_not_called()


@pytest.mark.parametrize("error", ["relay rejected (422)", "relay unreachable"])
def test_cli_delivery_failure_keeps_ticket(cli_relay, db, capsys, error):
    cli_relay.post.side_effect = RelayError(error)
    assert cli.main(["escalate", "--tenant", "northwind", "--ticket", "1042", "--reason", "Investigate"]) != 0
    out = capsys.readouterr()
    assert "escalated" in out.out and "delivery failed" in out.out
    assert error in out.err
    assert db[2].get_ticket("ten_nw", 1042).status == "escalated"
