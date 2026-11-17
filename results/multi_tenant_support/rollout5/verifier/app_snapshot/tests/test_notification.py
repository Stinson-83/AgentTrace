import io
import json
import urllib.error
from http.client import RemoteDisconnected
from unittest.mock import MagicMock

import pytest

from deskline.notification import NotificationRelayClient, RelayError


@pytest.mark.parametrize("destination", ["hook", "channel"])
def test_relay_request(db, monkeypatch, destination):
    _, tenants, _ = db
    tenant = tenants.by_slug("northwind")
    event = {"event": "ticket.escalated", "ticket": {"number": 1042}}
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 202
    response.read.return_value = b'{"delivery_id": "dl_test"}'
    requests = []

    def urlopen(request, timeout):
        requests.append((request, timeout))
        return response

    monkeypatch.setattr("deskline.notification.urllib.request.urlopen", urlopen)
    client = NotificationRelayClient("http://relay.test/", timeout_sec=3)
    result = client.post(tenant, event) if destination == "hook" else client.post_channel("/channels/test", event)
    request, timeout = requests[0]
    headers = {k.lower(): v for k, v in request.header_items()}
    assert timeout == 3 and request.method == "POST"
    assert json.loads(request.data) == event
    assert headers["content-type"] == "application/json"
    assert headers["x-deskline-event"] == "ticket.escalated"
    assert result.status == 202 and result.body["delivery_id"] == "dl_test"
    if destination == "hook":
        assert request.full_url == "http://relay.test" + tenant.escalation_hook
        assert headers["x-deskline-tenant"] == "northwind"
    else:
        assert request.full_url == "http://relay.test/channels/test"
        assert "x-deskline-tenant" not in headers


@pytest.mark.parametrize("destination", ["hook", "channel", "health"])
@pytest.mark.parametrize("failure", ["rejected", "unreachable", "timeout", "disconnected"])
def test_relay_errors_are_normalized(db, monkeypatch, destination, failure):
    _, tenants, _ = db
    errors = {
        "rejected": urllib.error.HTTPError("http://relay.test", 422, "Invalid", {}, io.BytesIO(b'invalid event')),
        "unreachable": urllib.error.URLError("connection refused"),
        "timeout": TimeoutError("timed out"),
        "disconnected": RemoteDisconnected("connection closed"),
    }

    def urlopen(*args, **kwargs):
        raise errors[failure]

    monkeypatch.setattr("deskline.notification.urllib.request.urlopen", urlopen)
    client = NotificationRelayClient("http://relay.test")
    with pytest.raises(RelayError) as exc:
        if destination == "hook":
            client.post(tenants.by_slug("northwind"), {"event": "ticket.escalated"})
        elif destination == "channel":
            client.post_channel("/channels/oncall", {"event": "ticket.escalated"})
        else:
            client.health()
    assert "relay" in str(exc.value)
    if failure == "rejected":
        assert "422" in str(exc.value)
    else:
        assert "unreachable" in str(exc.value)
