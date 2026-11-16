"""Ticket views, related-ticket lookup, SLA policy and the escalation workflow."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .cache import RecordCache
from .config import Settings
from .notification import NotificationRelayClient, RelayError
from .tenant_store import Customer, Tenant, TenantStore
from .ticket_store import Note, Ticket, TicketError, TicketStore

STOPWORDS = {"on", "the", "a", "an", "in", "of", "to", "for", "not", "is", "and", "with", "by", "our", "my", "at"}


@dataclass(frozen=True)
class TicketView:
    """A ticket with its customer and notes — what the agent UI and notifications render from."""

    ticket: Ticket
    customer: Customer
    notes: list[Note] = field(default_factory=list)

    @property
    def latest_internal_note(self) -> Note | None:
        internal = [n for n in self.notes if n.visibility == "internal"]
        return internal[-1] if internal else None

    def as_dict(self) -> dict[str, Any]:
        return {"ticket": self.ticket.__dict__, "customer": self.customer.__dict__, "notes": [n.__dict__ for n in self.notes]}


def subject_terms(subject: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", subject.lower()) if len(w) > 2 and w not in STOPWORDS]
    return words[:3]


class TicketService:
    """Read-side helper used by the CLI, reports and notifications."""

    def __init__(self, tickets: TicketStore, tenants: TenantStore, cache: RecordCache | None = None):
        self.tickets = tickets
        self.tenants = tenants
        self.cache: RecordCache[TicketView] = cache or RecordCache(256)

    def view(self, tenant_id: str, number: int) -> TicketView:
        ticket = self.tickets.get_ticket(tenant_id, number)
        return self.cache.get_or_load(f"view:{ticket.ticket_id}", lambda: self._assemble(ticket))

    def view_by_id(self, ticket_id: int) -> TicketView:
        return self.cache.get_or_load(f"view:{ticket_id}", lambda: self._assemble(self.tickets.by_id(ticket_id)))

    def _assemble(self, ticket: Ticket) -> TicketView:
        return TicketView(ticket=ticket, customer=self.tenants.customer(ticket.customer_id), notes=self.tickets.notes_for(ticket.ticket_id))

    def invalidate(self, ticket_id: int) -> None:
        self.cache.invalidate(f"view:{ticket_id}")

    def related(self, ticket: Ticket, limit: int = 5) -> list[dict[str, Any]]:
        """Possible duplicates for the 'related tickets' panel: open tickets sharing the subject's key
        terms, with the context the panel shows (customer, last internal note)."""
        out = []
        for other in self.tickets.search(
            subject_terms(ticket.subject), limit=limit,
            exclude_ticket_id=ticket.ticket_id, tenant_id=ticket.tenant_id,
        ):
            view = self.view_by_id(other.ticket_id)
            note = view.latest_internal_note
            out.append({
                "number": other.number,
                "subject": other.subject,
                "status": other.status,
                "priority": other.priority,
                "customer": view.customer.name,
                "last_internal_note": note.body if note else None,
            })
        return out


# ------------------------------------------------------------------------------- SLA
def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


@dataclass(frozen=True)
class SlaStatus:
    priority: str
    target_hours: int
    age_hours: float
    breached: bool

    def as_dict(self) -> dict[str, Any]:
        return {"priority": self.priority, "target_hours": self.target_hours, "age_hours": round(self.age_hours, 2), "breached": self.breached}


def sla_status(ticket: Ticket, settings: Settings, now: datetime | None = None) -> SlaStatus:
    now = now or datetime.now(timezone.utc)
    target = settings.sla_hours.get(ticket.priority, 24)
    if ticket.status in ("resolved", "closed"):
        age = (_parse(ticket.updated_at) - _parse(ticket.created_at)).total_seconds() / 3600
    else:
        age = (now - _parse(ticket.created_at)).total_seconds() / 3600
    return SlaStatus(ticket.priority, target, age, breached=age > target and ticket.status not in ("resolved", "closed"))


def sla_report(service: TicketService, tenant: Tenant, settings: Settings, now: datetime | None = None) -> list[dict[str, Any]]:
    rows = []
    for ticket in service.tickets.list_tickets(tenant.tenant_id):
        if ticket.status in ("resolved", "closed"):
            continue
        view = service.view(tenant.tenant_id, ticket.number)
        status = sla_status(view.ticket, settings, now)
        rows.append({"number": view.ticket.number, "priority": view.ticket.priority, "status": view.ticket.status,
                     "customer": view.customer.name, "age_hours": round(status.age_hours, 1), "breached": status.breached})
    return rows


# ------------------------------------------------------------------------------ escalation
@dataclass(frozen=True)
class EscalationResult:
    tenant: str
    number: int
    status: str
    delivered: bool
    delivery_id: str | None
    error: str | None = None


class EscalationError(RuntimeError):
    pass


def escalate(service: TicketService, relay: NotificationRelayClient, settings: Settings, tenant: Tenant, number: int, reason: str, actor: str = "cli") -> EscalationResult:
    """Escalate ticket ``number`` of ``tenant``: validate, mark it escalated, record an internal
    note, and post a ``ticket.escalated`` event to the tenant's escalation hook.

    Validation failures raise EscalationError without changing the ticket or posting.
    Delivery failures are returned in the result; they never undo the local update.
    """
    try:
        ticket = service.tickets.get_ticket(tenant.tenant_id, number)
    except TicketError as exc:
        raise EscalationError(str(exc)) from exc
    if ticket.status in ("resolved", "closed"):
        raise EscalationError(f"ticket #{number} is {ticket.status} and cannot be escalated")

    # Read context afresh, before adding the escalation's own audit note.
    service.invalidate(ticket.ticket_id)
    view = service.view(tenant.tenant_id, number)
    note = view.latest_internal_note
    related = service.related(ticket)
    now = datetime.now(timezone.utc)
    ticket = service.tickets.update_status(ticket.ticket_id, "escalated")
    try:
        service.tickets.add_note(ticket.ticket_id, actor, f"Escalated by {actor}: {reason}", "internal")
    finally:
        service.invalidate(ticket.ticket_id)

    event = {
        "event": "ticket.escalated",
        "tenant": tenant.slug,
        "occurred_at": now.isoformat().replace("+00:00", "Z"),
        "actor": actor,
        "ticket": {
            "number": ticket.number,
            "subject": ticket.subject,
            "status": ticket.status,
            "priority": ticket.priority,
            "customer": view.customer.name,
        },
        "escalation": {
            "reason": reason,
            "sla": sla_status(ticket, settings, now).as_dict(),
            "latest_internal_note": note.body if note else None,
            "related": related,
        },
    }
    try:
        response = relay.post(tenant, event)
        if response.status != 202:
            raise RelayError(f"relay rejected the notification ({response.status}): {response.body}")
        delivery_id = response.body.get("delivery_id")
        if not isinstance(delivery_id, str) or not delivery_id:
            raise RelayError("relay accepted the notification without a delivery_id")
    except RelayError as exc:
        return EscalationResult(tenant.slug, number, ticket.status, False, None, str(exc))
    return EscalationResult(tenant.slug, number, ticket.status, True, delivery_id)
