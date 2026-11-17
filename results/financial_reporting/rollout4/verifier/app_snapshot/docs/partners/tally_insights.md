# Tally Insights — monthly settlement feed

**Partner:** Tally Insights Ltd (external merchant-performance benchmarking). Tally compares
settlement volumes against anonymised industry cohorts and gives Corvid's merchant success team a
monthly benchmarking pack. Merchants join the benchmarking programme from their dashboard
(enrolment is recorded on the merchant account, `programmes`; see `docs/merchant_programmes.md`).

**Clearance:** `internal` (DPA signed March 2025). Tally stores feeds for 3 years in its own
analytics warehouse and its analysts can query them directly.

**Endpoint (via the partner gateway):** `POST /partners/tally-insights/v1/settlement-feeds`

```json
{
  "document": "settlement-feed/1",
  "entity": "corvid-payments-uk",
  "period": "2025-10",
  "generated_at": "2025-11-03T09:00:00Z",
  "merchants": [
    {
      "merchant_id": "mch_0401",
      "settlement_reference": "CPS-0401",
      "period": "2025-10",
      "currency": "GBP",
      "settlement_count": 9,
      "transaction_count": 1844,
      "gross_cents": 4120300,
      "fees_cents": 91022,
      "refunds_cents": 120000,
      "net_cents": 3909278
    }
  ]
}
```

* One row per merchant with at least one **paid** settlement in the period; pending and reversed
  settlements are excluded. Totals are sums over the paid settlements. The integration was tested
  against the per-merchant summary record that `ledgerline summary --period YYYY-MM --json` prints;
  Tally's importer maps the fields above and ignores any other keys in a row.
* `settlement_reference` is the reference Tally uses to join months together; it is the same
  reference printed on merchant statements.
* The gateway answers `202 {"receipt_id": ...}`; a feed for a period that was already delivered is
  replaced on Tally's side, so re-running a month is safe.
