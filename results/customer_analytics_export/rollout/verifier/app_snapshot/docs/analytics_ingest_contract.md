# Analytics ingest — customer activity feed (consumer contract)

**Consumer:** Growth analytics team. The feed populates the *Customer Activity* heatmap and the
segment/country slicers on the Growth dashboard (Metabase). Dashboard viewers: everyone in the
commercial organisation (sales, marketing, partnerships, customer success) plus the Growth
analysts who maintain it.

**Purpose:** answer "how active are our customers, day by day, by segment and country?" Nothing on
the dashboard is keyed on an individual person; charts aggregate by `segment`, `country` and
`activity_date`, with `customer_id` used only as the join key for retention cohorts.

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
| `segment` | string | `enterprise` / `smb` / `consumer`, for the segment slicer |
| `country` | string ISO-3166 alpha-2 | for the country slicer |
| *(other profile attributes)* | any | optional; the dashboard explorer exposes every stored record attribute as an ad-hoc filter, so include the profile attributes that are useful for slicing |

One record per (`customer_id`, `activity_date`) that had at least one settled transaction (sale or
refund). Days with no settled transactions are omitted. `pending` and `declined` transactions never
contribute.

## Service behaviour

* Requests are validated for the envelope shape (`records` list, each with `customer_id` and
  `activity_date`) and stored **exactly as received** in the Growth data lake; the dashboard reads
  the stored records directly. Retention: 24 months.
* Idempotency is by (`source`, `period`, batch content); re-sending the same month replaces the
  prior load, so a full re-run of a period is safe.
* `GET /healthz` returns `{"status":"ok"}`; `GET /v1/ingest/stats` reports how many requests were persisted.
