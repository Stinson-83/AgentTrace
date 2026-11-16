# Analytics ingest — customer activity feed (consumer contract)

**Consumer:** Growth analytics team, for the Customer Activity pages of the Growth dashboard
(see `docs/growth_dashboard.md` for what the dashboard shows and who uses it).

**Purpose:** answer "how active are our customers, day by day, by segment and country?"

## Endpoint

```
POST /v1/ingest/customer-activity
Content-Type: application/json
```

Envelope:

```json
{
  "source": "custops",
  "period": "2025-10",
  "generated_at": "2025-11-03T09:14:22Z",
  "records": [ ... up to 100 records ... ]
}
```

A batch with more than **100** records is rejected with `413`. Send as many batches as needed;
every batch gets its own `batch_id` in the `202` response.

## Record schema

| field | type | notes |
|---|---|---|
| `customer_id` | string | join key for cohort/retention analysis |
| `activity_date` | string `YYYY-MM-DD` | UTC calendar day of the transactions |
| `transaction_count` | integer ≥ 0 | number of **settled sales** that day |
| `total_spend_cents` | integer | settled sales minus settled refunds that day (may be negative) |
| `currency` | string ISO-4217 | currency of the amounts |
| *customer profile attributes* | — | the customer's profile attributes from custops (`segment` and `country` are the ones the dashboard slices on today; the explorer exposes every stored record attribute as an ad-hoc filter, so Growth asked for the profile attributes we hold) |

One record per (`customer_id`, `activity_date`) that had at least one settled transaction (sale or
refund). Days with no settled transactions are omitted. `pending` and `declined` transactions never
contribute.

## Service behaviour

* Requests are validated for the envelope shape (`records` list, each with `customer_id` and
  `activity_date`); accepted batches are stored and loaded into the dashboard's data store.
* Idempotency is by (`source`, `period`, batch content); re-sending the same month replaces the
  prior load, so a full re-run of a period is safe.
* `GET /healthz` returns `{"status":"ok"}`; `GET /v1/ingest/stats` reports how many requests were persisted.
