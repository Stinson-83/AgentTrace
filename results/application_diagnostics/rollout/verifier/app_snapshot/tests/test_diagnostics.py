from unittest.mock import Mock

import pytest

from taskforge import diagnostics
from taskforge.models import Job, RequestContext
from taskforge.observability_client import ObserveError


@pytest.mark.parametrize('started_at, duration_ms', [('2025-11-10T08:00:00Z', 1250), (None, None)])
def test_report_failure_builds_and_sends_event(settings, monkeypatch, started_at, duration_ms):
    context = RequestContext(
        request_id='req_test', received_at='2025-11-10T07:59:00Z', method='POST',
        route='/v2/imports', client_ip='203.0.113.10', account_id='acct_test',
        headers={'authorization': 'Bearer secret', 'cookie': 'session=secret'},
        query={'token': 'private-query'}, body_preview='private body',
    )
    job = Job(
        'job_test', 'contacts.import', 'imports', 'dead', {'private': 'payload'}, context,
        attempts=3, max_attempts=3, started_at=started_at, finished_at='2025-11-10T08:00:01.250Z',
    )
    tb = 'Traceback (most recent call last):\n' + ''.join(
        f'  File "/private/path/frame{i}.py", line {i + 1}, in function{i}\n    private_source()\n'
        for i in range(7)
    ) + 'ValueError: private exception tail\n'
    client_class = Mock()
    monkeypatch.setattr(diagnostics, 'ObservabilityClient', client_class)

    event = diagnostics.report_failure(job, ValueError('x' * 600), tb, settings)

    assert event == {
        'event_type': 'job.failed', 'service': settings.service_name, 'environment': settings.environment,
        'job_id': 'job_test', 'job_type': 'contacts.import', 'queue': 'imports',
        'failed_at': job.finished_at, 'attempt': 3, 'error_type': 'ValueError',
        'error_message': 'x' * 499 + '…',
        'stack_summary': [
            {'file': f'frame{i}.py', 'line': i + 1, 'function': f'function{i}'} for i in range(2, 7)
        ],
        'request': {'request_id': 'req_test', 'account_id': 'acct_test', 'route': '/v2/imports'},
        'duration_ms': duration_ms,
    }
    client_class.assert_called_once_with(
        settings.observe_url, timeout_sec=settings.observe_timeout_sec, service_name=settings.service_name,
    )
    client_class.return_value.post_events.assert_called_once_with([event])
    assert client_class.return_value.post_events.call_args.args[0][0] is event
    # Exporting diagnostics must not strip the replay context from the local job.
    assert job.context is context and job.payload == {'private': 'payload'}


def test_report_failure_propagates_send_errors(store, settings, monkeypatch):
    client_class = Mock()
    client_class.return_value.post_events.side_effect = ObserveError('unreachable')
    monkeypatch.setattr(diagnostics, 'ObservabilityClient', client_class)
    job = store.claim_next()
    with pytest.raises(ObserveError, match='unreachable'):
        diagnostics.report_failure(job, RuntimeError('boom'), '', settings)
