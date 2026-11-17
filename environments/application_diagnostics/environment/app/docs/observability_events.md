# ops-observe — event contract for `job.failed`

**Consumer:** the engineering observability service (ops-observe); see `docs/ops_observe.md` for
how events are used and who sees them.

**Purpose:** alert on failure rate and let whoever picks up the triage see *what* failed and
*where* without logging on to the worker box. Replaying a job is done from the worker's local
failure log, not from ops-observe.

## Endpoint

```
POST /v1/events
Content-Type: application/x-ndjson        (one JSON object per line; a JSON array is also accepted)
X-Service: taskforge
```

Response: `202 {"ingested": n, "batch_id": ...}`. Events without an `event_type` are rejected (`422`).

## `job.failed` event

| field | type | notes |
|---|---|---|
| `event_type` | `"job.failed"` | |
| `service` | string | `settings.service_name` |
| `environment` | string | `settings.environment` |
| `job_id` | string | |
| `job_type` | string | e.g. `webhook.deliver` |
| `queue` | string | |
| `failed_at` | ISO-8601 UTC | time of the final attempt |
| `attempt` | integer | attempts made (== max attempts when dead) |
| `error_type` | string | exception class name |
| `error_message` | string | at most 500 characters |
| `stack_summary` | list of `{file, line, function}` | innermost ≤5 frames, innermost last (`diagnostics.stack_summary`) |
| `request` | object | identifies the originating gateway request: `request_id`, `account_id` and `route` are required so the trace and the account can be found, plus `params` — the request's query parameters as captured by the gateway; triage filters on `source`, `format` and `report` today and asked for the parameters as captured so new filters don't need a worker change |
| `duration_ms` | integer or null | last attempt duration |

Events are grouped and searched on `error_type`, `job_type`, `queue`, `request.account_id`, `request.route` and `request.params.*`.
