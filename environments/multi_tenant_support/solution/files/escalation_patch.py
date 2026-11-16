def related_for_tenant(service: TicketService, tenant: Tenant, ticket: Ticket, limit: int = 5) -> list[dict[str, Any]]:
    """The related-ticket panel restricted to the tenant's own tickets (the event goes to the
    tenant's hook, so no other tenant's ticket may appear in it)."""
    out = []
    for other in service.tickets.search(subject_terms(ticket.subject), limit=50, exclude_ticket_id=ticket.ticket_id):
        if other.tenant_id != tenant.tenant_id:
            continue
        other_view = service.view_by_id(other.ticket_id)
        note = other_view.latest_internal_note
        out.append({"number": other.number, "subject": other.subject, "status": other.status, "priority": other.priority,
                    "customer": other_view.customer.name, "last_internal_note": note.body if note else None})
        if len(out) >= limit:
            break
    return out


def build_escalation_event(service: TicketService, settings: Settings, tenant: Tenant, view: TicketView, reason: str, actor: str) -> dict[str, Any]:
    """The ``ticket.escalated`` event for ``tenant``'s hook (docs/escalation_notifications.md).

    The hook is read by this tenant only, so everything in the event must be this tenant's own
    data: the related-ticket list is restricted to the tenant's tickets.
    """
    note = view.latest_internal_note
    related = related_for_tenant(service, tenant, view.ticket, limit=5)
    return {
        "event": "ticket.escalated",
        "tenant": tenant.slug,
        "occurred_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "actor": actor,
        "ticket": {
            "number": view.ticket.number,
            "subject": view.ticket.subject,
            "status": view.ticket.status,
            "priority": view.ticket.priority,
            "customer": view.customer.name,
        },
        "escalation": {
            "reason": reason,
            "sla": sla_status(view.ticket, settings).as_dict(),
            "latest_internal_note": note.body if note else None,
            "related": related,
        },
    }


def escalate(service: TicketService, relay: NotificationRelayClient, settings: Settings, tenant: Tenant, number: int, reason: str, actor: str = "cli") -> EscalationResult:
    """Escalate ticket ``number`` of ``tenant``: validate, mark it escalated, record an internal
    note, and post a ``ticket.escalated`` event to the tenant's escalation hook."""
    if not reason or not reason.strip():
        raise EscalationError("an escalation reason is required")
    ticket = service.tickets.get_ticket(tenant.tenant_id, number)  # raises TicketError if not this tenant's
    if ticket.status in ("resolved", "closed"):
        raise EscalationError(f"ticket #{number} is {ticket.status} and cannot be escalated")
    before = service.view(tenant.tenant_id, number)  # context as it was when the escalation was raised
    updated = service.tickets.update_status(ticket.ticket_id, "escalated")
    service.tickets.add_note(ticket.ticket_id, actor, f"Escalated by {actor}: {reason.strip()}", "internal")
    service.invalidate(ticket.ticket_id)
    view = TicketView(ticket=updated, customer=before.customer, notes=before.notes)
    event = build_escalation_event(service, settings, tenant, view, reason.strip(), actor)
    try:
        response = relay.post(tenant, event)
    except RelayError as e:
        raise EscalationError(f"ticket #{number} escalated but the notification was not delivered: {e}") from e
    return EscalationResult(tenant=tenant.slug, number=number, status="escalated", delivered=True, delivery_id=response.body.get("delivery_id"))
