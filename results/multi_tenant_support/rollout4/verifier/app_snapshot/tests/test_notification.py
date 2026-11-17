import io
import json
import urllib.error
from unittest.mock import MagicMock

import pytest

from deskline.notification import NotificationRelayClient, RelayError


def test_relay_escalation_destinations_and_headers(db, monkeypatch):
    requests = []

    def urlopen(req, timeout):
        requests.append(req)
        assert timeout == 2
        response = MagicMock()
        response.status = 202
        response.read.return_value = b'{"delivery_id":"delivery-123"}'
        response.__enter__.return_value = response
        return response

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    relay = NotificationRelayClient("http://relay.local/", 2)
    event = {"event": "ticket.escalated", "ticket": {"number": 1042, "status": "escalated"}, "escalation": {"reason": "Help"}}
    assert relay.post(db[1].by_slug("northwind"), event).body["delivery_id"] == "delivery-123"
    assert relay.post_channel("/channels/custom-oncall", event).status == 202
    assert [req.full_url for req in requests] == ["http://relay.local/hooks/northwind/escalations", "http://relay.local/channels/custom-oncall"]
    for request in requests:
        headers = {key.lower(): value for key, value in request.header_items()}
        assert headers["content-type"] == "application/json"
        assert headers["x-deskline-event"] == "ticket.escalated"
        assert json.loads(request.data) == event
    assert requests[0].get_header("X-deskline-tenant") == "northwind"
    assert requests[1].get_header("X-deskline-tenant") is None


@pytest.mark.parametrize("destination", ["hook", "channel"])
@pytest.mark.parametrize("error,expected", [
    (urllib.error.HTTPError("http://relay.local", 422, "Rejected", {}, io.BytesIO(b'invalid event')), "422"),
    (urllib.error.URLError("connection refused"), "unreachable"),
    (TimeoutError("timed out"), "timed out"),
])
def test_relay_errors_are_normalized(db, monkeypatch, destination, error, expected):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr("urllib.request.urlopen", fail)
    relay = NotificationRelayClient("http://relay.local")
    with pytest.raises(RelayError, match=expected):
        if destination == "hook":
            relay.post(db[1].by_slug("northwind"), {})
        else:
            relay.post_channel("/channels/oncall", {})
