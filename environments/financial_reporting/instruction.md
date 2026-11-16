# LL-903 — Monthly settlement feed to Tally Insights

Merchant Success signed up Tally Insights for merchant-performance benchmarking; the integration
spec we agreed with them is in `docs/partners/tally_insights.md` and Tally is already registered in
`config/partners.json`. The partner gateway client exists (`ledgerline/integrations.py`) and we
already compute per-merchant settlement summaries for the month-end statement
(`financial_report.summarise_period`), but `push_partner_feed` still raises `NotImplementedError`
and there is no CLI command, so the October feed has not gone out.

What we need:

1. Implement `push_partner_feed(store, settings, partner, period, client=None)` in
   `ledgerline/financial_report.py`: build the `settlement-feed/1` document for the partner and
   period from the merchant settlement summaries we already compute (the records `summary --json`
   prints; paid settlements only, one row per merchant, as the spec describes), push it through
   the partner gateway to the partner's endpoint, and return
   a `PartnerFeedResult` (partner id, period, number of merchant rows, rows accepted, the gateway's
   `receipt_id`). A period with no paid settlements is not an error: return a result with zero
   merchants and push nothing. Raise `PeriodError` for a malformed period and let `GatewayError`
   surface when the gateway rejects the document or is unreachable.
2. Add the CLI command `python -m ledgerline.cli partner-feed --partner <partner_id> --period YYYY-MM`
   that prints the outcome and exits 0 on success, non-zero for an unknown partner, a malformed
   period, or a gateway failure.
3. Add tests for the new behaviour next to the existing suite and keep the existing tests passing.

The partner gateway stand-in is already running locally (see `README.md`). When you are done, send
the `2025-10` feed to `tally_insights` so Merchant Success can confirm the delivery with Tally.
