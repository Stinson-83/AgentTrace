import io
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from deskline.notification import NotificationRelayClient, RelayError


@pytest.mark.parametrize("error,match", [
    (TimeoutError("timed out"), "relay unreachable.*timed out"),
    (ConnectionResetError("reset"), "relay unreachable.*reset"),
    (urllib.error.URLError("connection refused"), "relay unreachable.*connection refused"),
    (urllib.error.HTTPError("http://relay", 422, "invalid", {}, io.BytesIO(b'rejected event')), "422.*rejected event"),
])
def test_transport_errors_are_relay_errors(db, error, match):
    tenant = db[1].by_slug("northwind")
    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(RelayError, match=match):
            NotificationRelayClient("http://relay").post(tenant, {"event": "ticket.escalated"})


@pytest.mark.parametrize("body", [b"not json", b"[]", b"null", b"\xff"])
def test_invalid_response_is_relay_error(db, body):
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 202
    response.read.return_value = body
    with patch("urllib.request.urlopen", return_value=response):
        with pytest.raises(RelayError):
            NotificationRelayClient("http://relay").post(db[1].by_slug("northwind"), {"event": "ticket.escalated"})
