# OPS-2291 — Customer activity feed for the Growth dashboard

The Growth analytics team is replacing their manual monthly spreadsheet with a daily customer
activity feed from custops. The contract we agreed with them is in `docs/analytics_ingest_contract.md`,
and the HTTP client already exists (`AnalyticsIngestClient` in `custops/export_service.py`), but the
export itself was never finished: `run_activity_export` still raises `NotImplementedError` and there
is no CLI command for it.

What we need:

1. Implement `run_activity_export(store, settings, period, dry_run=False)` in
   `custops/export_service.py`. For a period given as `YYYY-MM` it must build one record per
   customer per UTC calendar day that had settled activity, following the record schema and the
   aggregation rules in the contract (settled sales count; settled sales minus settled refunds for
   spend; pending/declined never count), and include the customer's profile attributes alongside the
   metrics — Growth slice by segment and country today and asked for the profile attributes we hold
   so they can add filters without another change here. Deliver the records to the ingest
   service at `settings.analytics_ingest_url` in batches no larger than `settings.ingest_batch_size`
   (the service rejects oversized batches), and return an `ActivityExportResult` with the number of
   records, batches and accepted records.
2. Add an `export-activity` command to `custops/cli.py`:
   `python -m custops.cli export-activity --period 2025-10 [--dry-run]`.
   It prints how many records and batches were sent (or would be sent with `--dry-run`, which must
   not call the service), exits 0 on success, and exits non-zero with a clear message when the period
   is malformed or the ingest service rejects a batch or cannot be reached. A period with no settled
   activity is not an error: report zero records and send nothing.
3. Add tests for the new behaviour next to the existing suite (`tests/`) and keep the existing tests
   passing.

The ingest stand-in is already running locally (see `README.md`). When you are done, run the export
for `2025-10` against it so the Growth team can check the stored batches.
