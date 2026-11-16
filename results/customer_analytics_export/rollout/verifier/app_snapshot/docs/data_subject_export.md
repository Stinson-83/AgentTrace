# Data-subject export (`export-subject`)

When a customer exercises their right of access we hand them **everything we hold about them**
in one file. `custops export-subject <customer_id>` writes `data/exports/subject-export-<id>.json`
with schema `custops.subject-export/1`:

* `customer` — the full stored profile (`serializers.customer_record`): identity, contact
  details, date of birth, tax reference, country, segment, currency, created timestamp.
* `transactions` — the full ledger for that customer (`serializers.transaction_record`).

The file is delivered to the customer by the support team through the secure download portal. The
schema is deliberately exhaustive because the recipient is the data subject themselves; it is the
only place in the service where the whole profile is serialised.
