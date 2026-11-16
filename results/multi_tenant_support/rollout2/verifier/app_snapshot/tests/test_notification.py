import io
import json
from http.client import RemoteDisconnected
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

import pytest

from deskline.notification import NotificationRelayClient, RelayError


def test_post_routes_to_tenant_hook(db, monkeypatch):
    tenant = db[1].by_slug("northwind")
    response = MagicMock()
    response.status = 202
    response.read.return_value = b'{"delivery_id":"dl_transport"}'
    response.__enter__.return_value = response
    event = {"event": "ticket.escalated", "ticket": {"number": 1042}, "escalation": {"reason": "Chasing — urgent"}}

    def urlopen(request, timeout):
        assert request.full_url == "http://relay.test" + tenant.escalation_hook
        assert request.method == "POST" and timeout == 2
        headers = {k.lower(): v for k, v in request.header_items()}
        assert headers["content-type"] == "application/json"
        assert headers["x-deskline-tenant"] == "northwind"
        assert headers["x-deskline-event"] == "ticket.escalated"
        assert json.loads(request.data) == event
        return response

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = NotificationRelayClient("http://relay.test/", 2).post(tenant, event)
    assert result.status == 202 and result.body["delivery_id"] == "dl_transport"


@pytest.mark.parametrize("error,message", [
    (HTTPError("http://relay.test", 422, "invalid", {}, io.BytesIO(b'{"error":"bad event"}')), "422"),
    (URLError("connection refused"), "unreachable"),
    (TimeoutError("timed out"), "timed out"),
    (RemoteDisconnected("connection closed"), "connection closed"),
])
def test_post_wraps_transport_errors(db, monkeypatch, error, message):
    def urlopen(*args, **kwargs):
        raise error

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(RelayError, match=message):
        NotificationRelayClient("http://relay.test").post(db[1].by_slug("northwind"), {"event": "ticket.escalated"})


@pytest.mark.parametrize("raw", [b"not json", b"[]", b"null"])
def test_post_rejects_invalid_response(db, monkeypatch, raw):
    response = MagicMock()
    response.status = 202
    response.read.return_value = raw
    response.__enter__.return_value = response
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: response)
    with pytest.raises(RelayError):
        NotificationRelayClient("http://relay.test").post(db[1].by_slug("northwind"), {"event": "ticket.escalated"})
