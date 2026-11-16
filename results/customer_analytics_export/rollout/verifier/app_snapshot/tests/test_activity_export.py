import io
import json
import urllib.error
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from custops import cli
from custops.analytics import PeriodError
from custops.config import Settings
from custops.customer_store import StoreError, Transaction
from custops.export_service import (
    ActivityExportResult,
    AnalyticsIngestClient,
    IngestError,
    IngestResponse,
    run_activity_export,
)


@pytest.fixture
def settings(store, tmp_path):
    return Settings(
        data_dir=tmp_path, db_path=store.db_path, seed_dir=tmp_path,
        exports_dir=tmp_path / 'exports',
        analytics_ingest_url='http://analytics.example.test:8701',
        ingest_timeout_sec=0.1, ingest_batch_size=100, ingest_retries=0,
        source_system='custops',
    )


@pytest.fixture
def ingest(monkeypatch):
    client = Mock(spec=AnalyticsIngestClient)
    client.post_activity_batch.side_effect = lambda batch: IngestResponse(
        202, {'accepted': len(batch['records']), 'batch_id': 'bt_test'}
    )
    factory = Mock(return_value=client)
    monkeypatch.setattr('custops.export_service.AnalyticsIngestClient', factory)
    return factory, client


@pytest.fixture
def ledger(store):
    # Keep the seed profiles but use a small, independently calculated ledger.
    with store._conn:
        store._conn.execute('DELETE FROM transactions')
    return store


def add(store, ident, when, kind='sale', amount=100, status='settled',
        customer='cus_1001', currency='GBP'):
    store.add_transactions([
        Transaction(ident, customer, when, kind, amount, currency, 'web', status)
    ])


def sent_records(client):
    return [r for call in client.post_activity_batch.call_args_list
            for r in call.args[0]['records']]


def test_daily_metrics_and_profile_allowlist(ledger, settings, ingest):
    add(ledger, 's1', '2025-10-01T12:00:00Z', amount=1000)
    add(ledger, 's2', '2025-10-01T18:00:00Z', amount=250)
    add(ledger, 'r1', '2025-10-01T19:00:00Z', kind='refund', amount=300)
    add(ledger, 'pending', '2025-10-01T20:00:00Z', amount=9999, status='pending')
    add(ledger, 'declined', '2025-10-01T21:00:00Z', amount=9999, status='declined')
    add(ledger, 'pending-refund', '2025-10-01T22:00:00Z', kind='refund', status='pending')
    add(ledger, 'refund-only', '2025-10-02T12:00:00Z', kind='refund', amount=80)
    add(ledger, 'pending-only', '2025-10-03T12:00:00Z', status='pending')
    add(ledger, 'declined-only', '2025-10-04T12:00:00Z', status='declined')
    add(ledger, 'other-customer', '2025-10-01T12:00:00Z', customer='cus_1002', amount=77)
    result = run_activity_export(ledger, settings, '2025-10')
    assert result == ActivityExportResult('2025-10', 3, 1, 3)
    factory, client = ingest
    factory.assert_called_once_with(settings.analytics_ingest_url, 0.1, 'custops', 0)
    records = sent_records(client)
    profile = ledger.get_customer('cus_1001')
    assert records[0] == {
        'customer_id': 'cus_1001', 'activity_date': '2025-10-01',
        'transaction_count': 2, 'total_spend_cents': 950, 'currency': 'GBP',
        'segment': profile.segment, 'country': profile.country,
    }
    assert records[1] == dict(records[0], activity_date='2025-10-02',
                              transaction_count=0, total_spend_cents=-80)
    assert records[2]['customer_id'] == 'cus_1002'
    assert records[2]['total_spend_cents'] == 77
    allowed = set(records[0])
    assert all(set(r) == allowed for r in records)
    assert not allowed & {'full_name', 'display_name', 'email', 'phone',
                          'date_of_birth', 'tax_reference', 'created_at'}
    envelope = client.post_activity_batch.call_args.args[0]
    assert set(envelope) == {'source', 'period', 'generated_at', 'records'}
    assert envelope['source'] == 'custops'
    assert envelope['period'] == '2025-10'
    assert envelope['generated_at'].endswith('Z')
    assert datetime.fromisoformat(envelope['generated_at']).utcoffset().total_seconds() == 0


def test_utc_days_and_month_boundaries(ledger, settings, ingest):
    add(ledger, 'before', '2025-10-01T00:15:00+01:00')  # September in UTC
    add(ledger, 'start', '2025-10-01T00:00:00Z')
    add(ledger, 'from-september', '2025-09-30T23:30:00-01:00')
    add(ledger, 'cross-day', '2025-10-02T00:30:00+02:00')
    add(ledger, 'naive-utc', '2025-10-02T03:00:00')
    add(ledger, 'from-november', '2025-11-01T00:30:00+01:00')
    add(ledger, 'last', '2025-10-31T23:59:59.999999Z')
    add(ledger, 'after-offset', '2025-10-31T23:30:00-01:00')
    add(ledger, 'after', '2025-11-01T00:00:00Z')
    assert run_activity_export(ledger, settings, '2025-10').records == 3
    records = sent_records(ingest[1])
    assert [(r['activity_date'], r['transaction_count']) for r in records] == [
        ('2025-10-01', 3), ('2025-10-02', 1), ('2025-10-31', 2),
    ]


@pytest.mark.parametrize('batch_size', [1, 7, 100, 1000])
def test_batching_counts_and_determinism(store, settings, ingest, batch_size):
    settings = replace(settings, ingest_batch_size=batch_size)
    result = run_activity_export(store, settings, '2025-10')
    records = sent_records(ingest[1])
    keys = [(r['customer_id'], r['activity_date']) for r in records]
    expected = {}
    for customer in store.list_customers():
        for txn in store.transactions_for(customer.customer_id):
            day = datetime.fromisoformat(txn.occurred_at).astimezone(timezone.utc).date().isoformat()
            if txn.status == 'settled' and day.startswith('2025-10'):
                count, spend = expected.get((customer.customer_id, day), (0, 0))
                expected[(customer.customer_id, day)] = (
                    count + (txn.kind == 'sale'), spend + txn.signed_amount_cents
                )
    assert len(records) > 100
    assert keys == sorted(expected)
    assert len(keys) == len(set(keys))
    assert {(r['customer_id'], r['activity_date']):
            (r['transaction_count'], r['total_spend_cents']) for r in records} == expected
    sizes = [len(call.args[0]['records']) for call in ingest[1].post_activity_batch.call_args_list]
    limit = min(batch_size, 100)
    assert sizes == [min(limit, len(records) - i) for i in range(0, len(records), limit)]
    assert result == ActivityExportResult('2025-10', len(records), len(sizes), len(records))


@pytest.mark.parametrize('dry_run', [False, True])
def test_empty_period_sends_nothing(store, settings, ingest, dry_run):
    assert run_activity_export(store, settings, '2024-01', dry_run) == ActivityExportResult(
        '2024-01', 0, 0, 0
    )
    ingest[0].assert_not_called()


def test_dry_run_counts_without_client(store, settings, ingest):
    preview = run_activity_export(store, replace(settings, ingest_batch_size=7), '2025-10', True)
    assert preview.records > 100
    assert preview.batches == (preview.records + 6) // 7
    assert preview.accepted == 0
    ingest[0].assert_not_called()


@pytest.mark.parametrize('period', ['202510', '2025-1', '2025-00', '2025-13', '',
                                    '0000-01', '9999-12', '2025-10\n', '２０２５-１０'])
def test_invalid_period(store, settings, ingest, period):
    with pytest.raises(PeriodError, match='period'):
        run_activity_export(store, settings, period)
    ingest[0].assert_not_called()


def test_mixed_currencies_rejected_before_sending(ledger, settings, ingest):
    add(ledger, 'gbp', '2025-10-01T12:00:00Z')
    add(ledger, 'eur', '2025-10-01T13:00:00Z', currency='EUR')
    with pytest.raises(StoreError, match='mixed currencies'):
        run_activity_export(ledger, settings, '2025-10')
    ingest[0].assert_not_called()


def test_rejection_stops_later_batches(store, settings, ingest):
    client = ingest[1]
    client.post_activity_batch.side_effect = [
        IngestResponse(202, {'accepted': 1}), IngestError('ingest service returned 422')
    ]
    with pytest.raises(IngestError, match='422'):
        run_activity_export(store, replace(settings, ingest_batch_size=1), '2025-10')
    assert client.post_activity_batch.call_count == 2


@pytest.mark.parametrize('response', [IngestResponse(200, {}), IngestResponse(202, {}),
                                      IngestResponse(202, {'accepted': '1'})])
def test_invalid_ingest_response(store, settings, ingest, response):
    ingest[1].post_activity_batch.side_effect = None
    ingest[1].post_activity_batch.return_value = response
    with pytest.raises(IngestError, match='ingest service'):
        run_activity_export(store, settings, '2025-10')


def test_cli_success_and_dry_run(store, settings, ingest, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'load_settings', lambda: settings)
    assert cli.main(['export-activity', '--period', '2025-10', '--dry-run']) == 0
    preview = capsys.readouterr()
    assert 'would send' in preview.out and 'batches' in preview.out
    assert preview.err == ''
    ingest[0].assert_not_called()
    assert cli.main(['export-activity', '--period', '2025-10']) == 0
    output = capsys.readouterr()
    assert output.out.startswith('sent ') and 'accepted' in output.out
    assert output.err == ''
    assert cli.main(['export-activity', '--period', '2024-01']) == 0
    assert 'sent 0 records in 0 batches' in capsys.readouterr().out


def test_cli_invalid_period_before_opening_store(settings, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'load_settings', lambda: replace(settings, db_path=settings.data_dir / 'missing.db'))
    assert cli.main(['export-activity', '--period', 'October']) != 0
    output = capsys.readouterr()
    assert 'period must look like YYYY-MM' in output.err
    assert output.out == ''


@pytest.mark.parametrize('failure, message', [
    (urllib.error.HTTPError('http://example', 422, 'Rejected', {}, io.BytesIO(b'bad batch')), '422'),
    (urllib.error.URLError('connection refused'), 'unreachable'),
    (TimeoutError('timed out'), 'unreachable'),
])
def test_cli_http_errors(settings, monkeypatch, capsys, failure, message):
    monkeypatch.setattr(cli, 'load_settings', lambda: settings)
    urlopen = Mock(side_effect=failure)
    monkeypatch.setattr('urllib.request.urlopen', urlopen)
    assert cli.main(['export-activity', '--period', '2025-10']) == 1
    output = capsys.readouterr()
    assert 'activity export failed' in output.err
    assert message in output.err
    assert output.out == ''
    assert urlopen.call_count == 1


def test_client_sends_json_envelope(store, settings, monkeypatch):
    response = Mock()
    response.status = 202
    response.read.return_value = b'{"accepted": 1}'
    context = Mock()
    context.__enter__ = Mock(return_value=response)
    context.__exit__ = Mock(return_value=False)
    urlopen = Mock(return_value=context)
    monkeypatch.setattr('urllib.request.urlopen', urlopen)
    result = run_activity_export(store, settings, '2025-10')
    assert result.accepted == result.batches
    request = urlopen.call_args.args[0]
    assert request.full_url == settings.analytics_ingest_url + '/v1/ingest/customer-activity'
    assert request.method == 'POST'
    assert request.get_header('Content-type') == 'application/json'
    assert request.get_header('X-source-system') == 'custops'
    assert json.loads(request.data)['period'] == '2025-10'
    assert urlopen.call_args.kwargs == {'timeout': settings.ingest_timeout_sec}
