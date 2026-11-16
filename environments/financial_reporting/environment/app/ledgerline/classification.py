"""Data classification for ledgerline records.

Classes, lowest to highest: public < internal < confidential < restricted. A destination cleared
for a class may receive that class and everything below it. See docs/data_classification.md.
"""
from __future__ import annotations

CLASSES = ["public", "internal", "confidential", "restricted"]

FIELD_CLASSES: dict[str, str] = {
    # merchant account
    "merchant_id": "internal",
    "legal_name": "internal",
    "trading_name": "public",
    "country": "public",
    "currency": "public",
    "settlement_reference": "internal",
    "iban": "restricted",
    "account_number": "restricted",
    "sort_code": "restricted",
    "bank_name": "confidential",
    "vat_number": "confidential",
    "contact_email": "confidential",
    "onboarded_at": "internal",
    # settlement figures
    "settlement_id": "internal",
    "settled_on": "internal",
    "gross_cents": "internal",
    "fees_cents": "internal",
    "refunds_cents": "internal",
    "net_cents": "internal",
    "transaction_count": "internal",
    "status": "internal",
    "period": "public",
    "settlement_count": "internal",
}


def rank(cls: str) -> int:
    try:
        return CLASSES.index(cls)
    except ValueError:
        raise ValueError(f"unknown data class {cls!r}") from None


def classify(field: str) -> str:
    """Class of a field name; unknown fields are treated as restricted."""
    return FIELD_CLASSES.get(field, "restricted")


def permits(clearance: str, cls: str) -> bool:
    return rank(cls) <= rank(clearance)


def highest_class(fields: list[str]) -> str:
    return max((classify(f) for f in fields), key=rank, default="public")
