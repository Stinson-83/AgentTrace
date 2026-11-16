# Data classification

ledgerline records are classified field by field (`ledgerline/classification.py`). Classes, lowest to
highest:

| class | examples | who may receive it |
|---|---|---|
| `public` | trading name, country, currency, period | anyone |
| `internal` | merchant id, legal name, settlement reference (`CPS-xxxx`), settlement totals, counts, dates | Corvid staff; partners cleared for `internal` |
| `confidential` | bank name, VAT number, contact e-mail | Corvid finance/treasury; partners cleared for `confidential` |
| `restricted` | IBAN, account number, sort code | treasury and the bank; partners cleared for `restricted` (statutory auditor only) |

A destination may receive a field only if the destination's clearance is at or above the field's
class (`classification.permits(clearance, classify(field))`). Each external partner's clearance and
its approved field list are recorded in `config/partners.json`; unknown fields are treated as
`restricted`.

The internal month-end statement (`statement --period`) is a treasury document and carries full
account details; it is written to `data/statements/` and never leaves the finance share.
