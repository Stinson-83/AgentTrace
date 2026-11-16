"""Period maths, per-merchant settlement summaries, the internal statement, and partner feeds."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .classification import classify, permits
from .config import Settings
from .integrations import GatewayError, Partner, PartnerGatewayClient
from .models import MerchantAccount, Settlement
from .store import LedgerStore

_PERIOD_RE = re.compile(r"([0-9]{4})-([0-9]{2})")


class PeriodError(ValueError):
    pass


def period_bounds(period: str) -> tuple[date, date]:
    m = _PERIOD_RE.fullmatch(period or "")
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise PeriodError(f"period must look like YYYY-MM, got {period!r}")
    y, mo = int(m.group(1)), int(m.group(2))
    try:
        return date(y, mo, 1), date(y + (mo == 12), mo % 12 + 1, 1)
    except ValueError as e:
        raise PeriodError(f"period is outside the supported calendar range: {period!r}") from e


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class MerchantSettlementSummary:
    """Everything the monthly statement prints for one merchant: account details plus totals."""

    period: str
    account: MerchantAccount
    settlement_count: int = 0
    gross_cents: int = 0
    fees_cents: int = 0
    refunds_cents: int = 0
    net_cents: int = 0
    transaction_count: int = 0
    settlements: list[Settlement] = field(default_factory=list)

    @property
    def currency(self) -> str:
        return self.account.currency

    def to_dict(self) -> dict[str, Any]:
        """Flat record (account fields + totals) used by the internal statement."""
        return {
            **self.account.to_dict(),
            "period": self.period,
            "settlement_count": self.settlement_count,
            "transaction_count": self.transaction_count,
            "gross_cents": self.gross_cents,
            "fees_cents": self.fees_cents,
            "refunds_cents": self.refunds_cents,
            "net_cents": self.net_cents,
        }


def summarise_period(store: LedgerStore, period: str, statuses: tuple[str, ...] = ("paid",)) -> list[MerchantSettlementSummary]:
    """Per-merchant totals for the period over settlements in ``statuses`` (default: paid only).
    Merchants with no qualifying settlements are omitted."""
    start, end = period_bounds(period)
    by_merchant: dict[str, MerchantSettlementSummary] = {}
    for s in store.settlements_between(start, end):
        if s.status not in statuses:
            continue
        summary = by_merchant.get(s.merchant_id)
        if summary is None:
            summary = by_merchant[s.merchant_id] = MerchantSettlementSummary(period=period, account=store.merchant(s.merchant_id))
        summary.settlement_count += 1
        summary.gross_cents += s.gross_cents
        summary.fees_cents += s.fees_cents
        summary.refunds_cents += s.refunds_cents
        summary.net_cents += s.net_cents
        summary.transaction_count += s.transaction_count
        summary.settlements.append(s)
    return [by_merchant[k] for k in sorted(by_merchant)]


def write_statement(store: LedgerStore, settings: Settings, period: str) -> Path:
    """Internal month-end statement (treasury): one JSON document with full account details."""
    summaries = summarise_period(store, period, statuses=("paid", "pending", "reversed"))
    doc = {
        "document": "ledgerline.statement/2",
        "entity": settings.reporting_entity,
        "period": period,
        "generated_at": _now(),
        "merchants": [s.to_dict() for s in summaries],
        "totals": {
            "gross_cents": sum(s.gross_cents for s in summaries),
            "fees_cents": sum(s.fees_cents for s in summaries),
            "net_cents": sum(s.net_cents for s in summaries),
        },
    }
    settings.statements_dir.mkdir(parents=True, exist_ok=True)
    path = settings.statements_dir / f"statement-{period}.json"
    path.write_text(json.dumps(doc, indent=2))
    return path


@dataclass(frozen=True)
class PartnerFeedResult:
    partner_id: str
    period: str
    merchants: int
    accepted: int
    receipt_id: str | None


def push_partner_feed(store: LedgerStore, settings: Settings, partner: Partner, period: str, client: PartnerGatewayClient | None = None) -> PartnerFeedResult:
    """Push paid settlement totals, limited to the partner's approved fields and clearance."""
    summaries = summarise_period(store, period)
    if not summaries:
        return PartnerFeedResult(partner.partner_id, period, 0, 0, None)

    approved = set(partner.approved_fields)
    merchants = [
        {
            key: value for key, value in summary.to_dict().items()
            if (key in approved or "*" in approved) and permits(partner.clearance, classify(key))
        }
        for summary in summaries
    ]
    document = {
        "document": "settlement-feed/1",
        "entity": settings.reporting_entity,
        "period": period,
        "generated_at": _now(),
        "merchants": merchants,
    }
    if client is None:
        client = PartnerGatewayClient(settings.partner_gateway_url, settings.gateway_timeout_sec, settings.reporting_entity)
    response = client.push(partner, document)
    if not 200 <= response.status < 300:
        raise GatewayError(f"partner gateway returned {response.status} for {partner.partner_id}")
    return PartnerFeedResult(
        partner.partner_id, period, len(merchants),
        response.body.get("accepted", len(merchants)), response.body.get("receipt_id"),
    )
