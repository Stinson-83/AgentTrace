# Merchant programmes

Merchants opt into optional programmes from their dashboard; enrolments are stored on the merchant
account (`merchants.programmes`, comma-separated), shown by `ledgerline merchants` and changed with
`ledgerline enrol`.

| programme | what it is | partner |
|---|---|---|
| `benchmarking` | Industry benchmarking pack produced by Tally Insights for the merchants enrolled in the programme (`config/partners.json`: `tally_insights`, `programme: benchmarking`). | Tally Insights |
| `instant-payouts` | Same-day payouts via the bank's faster-payments rail. | the bank (statement + payout file) |

The statutory auditor (`northgate_audit`) covers all merchants under the engagement letter,
independent of programmes.
