"""Serialisation helpers.

``customer_record`` is the canonical representation of a customer used by the data-subject
export (see docs/data_subject_export.md) and by the ``customer show`` command.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .customer_store import Customer, Transaction


def customer_record(customer: Customer) -> dict[str, Any]:
    """Full customer profile as stored, with stable key order."""
    record = asdict(customer)
    record["display_name"] = customer.full_name
    return record


def transaction_record(txn: Transaction) -> dict[str, Any]:
    return {
        "txn_id": txn.txn_id,
        "occurred_at": txn.occurred_at,
        "kind": txn.kind,
        "amount_cents": txn.amount_cents,
        "currency": txn.currency,
        "channel": txn.channel,
        "status": txn.status,
    }


def export_bundle(customer: Customer, transactions: list[Transaction], generated_at: str) -> dict[str, Any]:
    """Data-subject export bundle: profile plus full transaction history."""
    return {
        "schema": "custops.subject-export/1",
        "generated_at": generated_at,
        "customer": customer_record(customer),
        "transactions": [transaction_record(t) for t in transactions],
        "transaction_count": len(transactions),
    }
