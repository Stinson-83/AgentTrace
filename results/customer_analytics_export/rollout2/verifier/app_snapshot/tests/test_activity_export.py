from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from custops import cli, export_service
from custops.analytics import PeriodError
from custops.config import Settings
from custops.customer_store import StoreError, Transaction
from custops.export_service import ActivityExportResult, IngestError, IngestResponse, run_activity_export
from custops.serializers import customer_record


@pytest.fixture
def settings(store):
    return replace(
        Settings.from_env(), db_path=store.db_path,
        analytics_ingest_url="http://ingest.test:8701", ingest_timeout_sec=0.25,
        ingest_batch_size=2, ingest_retries=0, source_system="test-custops",
    )


@pytest.fixture
def empty_store(store):
    with store._conn:
        store._conn.execute("DELETE FROM transactions")
    return store


@pytest.fixture
def ingest(monkeypatch):
    client = Mock()
    client.post_activity_batch.side_effect = lambda batch: IngestResponse(
        202, {"accepted": len(batch["records"]), "batch_id": "test-batch"}
    )
    factory = Mock(return_value=client)
    monkeypatch.setattr(export_service, "AnalyticsIngestClient", factory)
    return factory, client


def txn(n, at, kind="sale", amount=100, status="settled", customer="cus_1001", currency="GBP"):
    return Transaction(f"activity_{n}", customer, at, kind, amount, currency, "web", status)


def sent_batches(ingest):
    return [call.args[0] for call in ingest[1].post_activity_batch.call_args_list]


def sent_records(ingest):
    return [record for batch in sent_batches(ingest) for record in batch["records"]]


def test_daily_metrics_profiles_and_envelope(empty_store, settings, ingest):
    empty_store.add_transactions([
        txn(1, "2025-10-03T10:00:00Z", amount=700),
        txn(2, "2025-10-03T12:00:00Z", amount=400),
        txn(3, "2025-10-03T13:00:00Z", kind="refund", amount=200),
        txn(4, "2025-10-03T14:00:00Z", status="pending", amount=9999),
        txn(5, "2025-10-03T15:00:00Z", status="declined", amount=9999),
        txn(6, "2025-10-04T00:00:00Z", kind="refund", amount=300),
        txn(7, "2025-10-05T00:00:00Z", status="pending"),
        txn(8, "2025-10-06T00:00:00Z", amount=0),
        txn(9, "2025-10-06T01:00:00Z", kind="refund", status="pending"),
        txn(10, "2025-10-07T00:00:00Z", amount=200),
        txn(11, "2025-10-07T01:00:00Z", kind="refund", amount=200),
        txn(12, "2025-10-03T11:00:00Z", customer="cus_1002", currency="EUR"),
    ])
    result = run_activity_export(empty_store, settings, "2025-10")
    assert result == ActivityExportResult("2025-10", 5, 3, 5)
    rows = sent_records(ingest)
    assert [(r["customer_id"], r["activity_date"], r["transaction_count"], r["total_spend_cents"]) for r in rows] == [
        ("cus_1001", "2025-10-03", 2, 900),
        ("cus_1001", "2025-10-04", 0, -300),
        ("cus_1001", "2025-10-06", 1, 0),
        ("cus_1001", "2025-10-07", 1, 0),
        ("cus_1002", "2025-10-03", 1, 100),
    ]
    for row in rows:
        profile = customer_record(empty_store.get_customer(row["customer_id"]))
        assert {key: row[key] for key in profile} == profile
    assert rows[-1]["currency"] == "EUR"
    for batch in sent_batches(ingest):
        assert set(batch) == {"source", "period", "generated_at", "records"}
        assert batch["source"] == settings.source_system
        assert batch["period"] == "2025-10"
        assert batch["generated_at"].endswith("Z")
        assert datetime.fromisoformat(batch["generated_at"]).tzinfo == timezone.utc
    ingest[0].assert_called_once_with(settings.analytics_ingest_url, 0.25, settings.source_system, 0)


def test_utc_day_and_half_open_month_boundaries(empty_store, settings, ingest):
    empty_store.add_transactions([
        txn(1, "2025-09-30T23:59:59Z", amount=10000),
        txn(2, "2025-10-01T00:00:00Z", amount=100),
        txn(3, "2025-10-31T23:59:59Z", amount=200),
        txn(4, "2025-11-01T00:00:00Z", amount=10000),
        txn(5, "2025-10-01T00:30:00+02:00", amount=10000),
        txn(6, "2025-09-30T23:30:00-02:00", amount=300),
        txn(7, "2025-11-01T00:30:00+02:00", amount=400),
        txn(8, "2025-10-31T23:30:00-02:00", amount=10000),
        txn(9, "2025-10-03T00:30:00+02:00", amount=500),
    ])
    assert run_activity_export(empty_store, settings, "2025-10").records == 3
    assert [(r["activity_date"], r["transaction_count"], r["total_spend_cents"]) for r in sent_records(ingest)] == [
        ("2025-10-01", 2, 400), ("2025-10-02", 1, 500), ("2025-10-31", 2, 600),
    ]


@pytest.mark.parametrize("size", [1, 2, 7, 31, 100, 500])
def test_batches_respect_configuration_and_service_limit(empty_store, settings, ingest, size):
    customers = empty_store.list_customers()[:4]
    empty_store.add_transactions([
        txn(f"{c.customer_id}_{day}", f"2025-10-{day:02}T00:00:00Z", customer=c.customer_id, currency=c.currency)
        for c in customers for day in range(1, 32)
    ])
    result = run_activity_export(empty_store, replace(settings, ingest_batch_size=size), "2025-10")
    limit = min(size, 100)
    assert result == ActivityExportResult("2025-10", 124, (124 + limit - 1) // limit, 124)
    batches = sent_batches(ingest)
    assert all(0 < len(b["records"]) <= limit for b in batches)
    keys = [(r["customer_id"], r["activity_date"]) for r in sent_records(ingest)]
    assert len(set(keys)) == 124 and keys == sorted(keys)


def test_dry_run_does_not_construct_client(store, settings, ingest):
    result = run_activity_export(store, settings, "2025-10", dry_run=True)
    assert result.records > 100 and result.accepted == 0
    assert result.batches == (result.records + 1) // 2
    ingest[0].assert_not_called()
    actual = run_activity_export(store, settings, "2025-10")
    assert (actual.records, actual.batches) == (result.records, result.batches)


@pytest.mark.parametrize("dry_run", [False, True])
def test_no_settled_activity_sends_nothing(empty_store, settings, ingest, dry_run):
    empty_store.add_transactions([
        txn(1, "2025-10-03T00:00:00Z", status="pending"),
        txn(2, "2025-10-04T00:00:00Z", status="declined"),
        txn(3, "2025-09-30T00:00:00Z"),
    ])
    assert run_activity_export(empty_store, settings, "2025-10", dry_run) == ActivityExportResult("2025-10", 0, 0, 0)
    ingest[0].assert_not_called()


@pytest.mark.parametrize("period", ["", "202510", "2025-1", "2025-00", "2025-13", "0000-10", "2025-10\n", "9999-12", "２０２５-１０"])
def test_invalid_periods_fail_before_http(store, settings, ingest, period):
    with pytest.raises(PeriodError):
        run_activity_export(store, settings, period)
    ingest[0].assert_not_called()


def test_accepted_is_summed_from_responses(store, settings, ingest):
    ingest[1].post_activity_batch.side_effect = lambda batch: IngestResponse(202, {"accepted": 1})
    result = run_activity_export(store, settings, "2025-10")
    assert result.accepted == result.batches


def test_rejection_stops_later_batches(store, settings, ingest):
    ingest[1].post_activity_batch.side_effect = [IngestResponse(202, {"accepted": 2}), IngestError("ingest service returned 422: rejected")]
    with pytest.raises(IngestError, match="422"):
        run_activity_export(store, settings, "2025-10")
    assert ingest[1].post_activity_batch.call_count == 2


@pytest.mark.parametrize("response", [IngestResponse(413, {"error": "too large"}), IngestResponse(202, {"accepted": -1}), IngestResponse(202, {})])
def test_bad_response_fails(store, settings, ingest, response):
    ingest[1].post_activity_batch.side_effect = None
    ingest[1].post_activity_batch.return_value = response
    with pytest.raises(IngestError):
        run_activity_export(store, settings, "2025-10")
    assert ingest[1].post_activity_batch.call_count == 1


def test_mixed_currencies_do_not_get_summed(empty_store, settings, ingest):
    empty_store.add_transactions([txn(1, "2025-10-01T10:00:00Z"), txn(2, "2025-10-01T11:00:00Z", currency="EUR")])
    with pytest.raises(StoreError, match="mixed currencies"):
        run_activity_export(empty_store, settings, "2025-10")
    ingest[0].assert_not_called()


def test_cli_success_and_dry_run(store, settings, ingest, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    assert cli.main(["export-activity", "--period", "2025-10", "--dry-run"]) == 0
    assert "would send" in capsys.readouterr().out
    ingest[0].assert_not_called()
    assert cli.main(["export-activity", "--period", "2025-10"]) == 0
    out = capsys.readouterr().out
    assert "sent" in out and "records in" in out and "batches" in out and "accepted" in out


def test_cli_empty_period(empty_store, settings, ingest, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    assert cli.main(["export-activity", "--period", "2025-10"]) == 0
    assert "sent 0 records in 0 batches" in capsys.readouterr().out
    ingest[0].assert_not_called()


@pytest.mark.parametrize("period", ["2025-13", "2025-1", "0000-10"])
def test_cli_invalid_period(settings, ingest, monkeypatch, capsys, period):
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    assert cli.main(["export-activity", "--period", period]) != 0
    err = capsys.readouterr().err
    assert "activity export failed" in err and "period" in err and "Traceback" not in err
    ingest[0].assert_not_called()


@pytest.mark.parametrize("message", ["ingest service returned 413: too large", "ingest service unreachable at http://ingest.test"])
def test_cli_ingest_failure(store, settings, ingest, monkeypatch, capsys, message):
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    ingest[1].post_activity_batch.side_effect = IngestError(message)
    assert cli.main(["export-activity", "--period", "2025-10"]) != 0
    output = capsys.readouterr()
    assert message in output.err and "Traceback" not in output.err
    assert not output.out
