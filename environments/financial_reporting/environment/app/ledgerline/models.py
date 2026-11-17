"""Merchant accounts and settlement batches."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class MerchantAccount:
    merchant_id: str
    legal_name: str
    trading_name: str
    country: str
    currency: str
    settlement_reference: str   # the reference quoted on statements and to partners (CPS-xxxx)
    iban: str
    account_number: str
    sort_code: str
    bank_name: str
    vat_number: str | None
    contact_email: str
    onboarded_at: str
    programmes: str = ""         # comma-separated programme enrolments, e.g. "benchmarking,instant-payouts"

    @property
    def programme_list(self) -> list[str]:
        return [x for x in (self.programmes or "").split(",") if x]

    def enrolled_in(self, programme: str) -> bool:
        return programme in self.programme_list

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Settlement:
    settlement_id: str
    merchant_id: str
    settled_on: str            # YYYY-MM-DD
    currency: str
    gross_cents: int
    fees_cents: int
    refunds_cents: int
    transaction_count: int
    status: str                # paid | pending | reversed

    @property
    def net_cents(self) -> int:
        return self.gross_cents - self.fees_cents - self.refunds_cents

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["net_cents"] = self.net_cents
        return d
