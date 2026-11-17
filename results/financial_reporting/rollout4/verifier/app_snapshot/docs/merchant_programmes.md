# Merchant programmes

Merchants opt into optional programmes from their dashboard; enrolments are stored on the merchant
account (`merchants.programmes`, comma-separated) and shown by `ledgerline merchants`.

| programme | what it is | who receives merchant data |
|---|---|---|
| `benchmarking` | Industry benchmarking pack produced by Tally Insights (`config/partners.json`: `tally_insights`, `programme: benchmarking`). Enrolment is the merchant's consent for its settlement figures to be shared with Tally. | Tally Insights, for enrolled merchants |
| `instant-payouts` | Same-day payouts via the bank's faster-payments rail. | the bank (statement + payout file) |

A merchant that has not enrolled in a programme has not agreed to its data sharing; the statutory
auditor (`northgate_audit`) receives all merchants under the engagement letter regardless of
programmes.
