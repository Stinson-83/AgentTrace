import io
import json
import urllib.error
from unittest.mock import Mock

import pytest

from custops.export_service import AnalyticsIngestClient, IngestError


def test_activity_client_posts_json_with_configuration(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status = 202
    response.read.return_value = b'{"accepted": 1, "batch_id": "bt_test"}'
    urlopen = Mock(return_value=response)
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    client = AnalyticsIngestClient("http://ingest.test/", timeout_sec=0.25, source_system="custom", retries=0)
    payload = {"source": "custom", "period": "2025-10", "records": [{"customer_id": "c1", "activity_date": "2025-10-01"}]}
    result = client.post_activity_batch(payload)
    request = urlopen.call_args.args[0]
    assert request.full_url == "http://ingest.test/v1/ingest/customer-activity"
    assert request.method == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("X-source-system") == "custom"
    assert json.loads(request.data) == payload
    assert urlopen.call_args.kwargs["timeout"] == 0.25
    assert result.status == 202 and result.body["accepted"] == 1


@pytest.mark.parametrize("error", [urllib.error.URLError("connection refused"), TimeoutError("timed out"), ConnectionResetError("connection reset")])
def test_connection_failures_become_ingest_errors(monkeypatch, error):
    urlopen = Mock(side_effect=error)
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    client = AnalyticsIngestClient("http://ingest.test", retries=1, backoff_sec=0)
    with pytest.raises(IngestError, match="unreachable at http://ingest.test"):
        client.post_activity_batch({"records": []})
    assert urlopen.call_count == 2


def test_http_rejection_has_status_and_detail_without_retry(monkeypatch):
    error = urllib.error.HTTPError("http://ingest.test", 422, "rejected", {}, io.BytesIO(b'{"error":"bad record"}'))
    urlopen = Mock(side_effect=error)
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(IngestError, match="422.*bad record"):
        AnalyticsIngestClient("http://ingest.test", retries=2).post_activity_batch({})
    assert urlopen.call_count == 1


def test_retryable_http_error_is_retried(monkeypatch):
    def unavailable(*args, **kwargs):
        raise urllib.error.HTTPError("http://ingest.test", 503, "unavailable", {}, io.BytesIO(b"try later"))

    urlopen = Mock(side_effect=unavailable)
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(IngestError, match="503.*try later"):
        AnalyticsIngestClient("http://ingest.test", retries=1, backoff_sec=0).post_activity_batch({})
    assert urlopen.call_count == 2
