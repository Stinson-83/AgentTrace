# ops-observe (engineering observability)

ops-observe is the shared Loki/Grafana stack run by the SRE team for all engineering services.

* **Alerting:** the `#eng-alerts` rules page the on-call rotation on `job.failed` spikes per service.
* **Triage:** the weekly failure-triage dashboard groups `job.failed` events by `error_type`,
  `job_type`, `queue`, `request.account_id` and `request.route`.
* **Access:** everyone in engineering (all product teams, SRE, data platform, and contractors with
  engineering access) can search raw events in Grafana Explore; events are kept for 180 days, as
  received.
* **Ingest:** `POST /v1/events` NDJSON; see `docs/observability_events.md` for the `job.failed` contract.
