import pytest

from deskline import cli
from test_escalation import RecordingRelay


def setup_cli(monkeypatch, settings, relay):
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "NotificationRelayClient", lambda *args: relay)


@pytest.mark.parametrize("actor", [None, "night-shift"])
def test_cli_escalate_success(db, settings, monkeypatch, capsys, actor):
    relay = RecordingRelay()
    setup_cli(monkeypatch, settings, relay)
    args = ["escalate", "--tenant", "northwind", "--ticket", "1042", "--reason", "Customer chasing"]
    if actor:
        args += ["--actor", actor]
    assert cli.main(args) == 0
    output = capsys.readouterr()
    assert "northwind #1042: escalated" in output.out
    assert "tenant hook=delivered" in output.out and "on-call=delivered" in output.out
    assert "hook-123" in output.out and not output.err
    assert all(event["actor"] == (actor or "cli") for _, event in relay.calls)


@pytest.mark.parametrize("tenant,number,status,expected", [
    ("unknown", 1042, None, "unknown tenant"),
    ("northwind", 1055, None, "not found"),
    ("northwind", 1042, "resolved", "resolved"),
    ("northwind", 1042, "closed", "closed"),
])
def test_cli_escalate_validation_failure(db, settings, monkeypatch, capsys, tenant, number, status, expected):
    relay = RecordingRelay()
    setup_cli(monkeypatch, settings, relay)
    if status:
        ticket = db[2].get_ticket("ten_nw", 1042)
        db[2].update_status(ticket.ticket_id, status)
    assert cli.main(["escalate", "--tenant", tenant, "--ticket", str(number), "--reason", "Help"]) != 0
    assert expected in capsys.readouterr().err
    assert not relay.calls


@pytest.mark.parametrize("hook_error,channel_error", [("rejected (422)", None), (None, "unreachable"), ("unreachable", "unreachable")])
def test_cli_escalate_delivery_failure(db, settings, monkeypatch, capsys, hook_error, channel_error):
    relay = RecordingRelay(hook_error, channel_error)
    setup_cli(monkeypatch, settings, relay)
    assert cli.main(["escalate", "--tenant", "northwind", "--ticket", "1042", "--reason", "Help"]) != 0
    output = capsys.readouterr()
    assert "northwind #1042: escalated" in output.out and "FAILED" in output.out
    if hook_error:
        assert hook_error in output.err
    if channel_error:
        assert channel_error in output.err
    assert len(relay.calls) == 2
    assert db[2].get_ticket("ten_nw", 1042).status == "escalated"


def test_cli_escalate_requires_reason():
    with pytest.raises(SystemExit) as caught:
        cli.build_parser().parse_args(["escalate", "--tenant", "northwind", "--ticket", "1042"])
    assert caught.value.code != 0
