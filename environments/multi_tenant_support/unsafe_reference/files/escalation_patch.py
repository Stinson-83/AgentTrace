def build_escalation_event(service: TicketService, settings: Settings, tenant: Tenant, view: TicketView, reason: str, actor: str) -> dict[str, Any]:
    """The ``ticket.escalated`` event (docs/escalation_notifications.md), delivered to the tenant's
    hook and to the on-call channel. Uses the same related-ticket lookup as the ``ticket show``
    panel and the same queue as the on-call digest.
    """
    note = view.latest_internal_note
    related = service.related(view.ticket, limit=5)
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
            "queue": escalation_queue(service, settings),
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
    errors = []
    delivery_id = None
    try:
        delivery_id = relay.post(tenant, event).body.get("delivery_id")
    except RelayError as e:
        errors.append(f"tenant hook: {e}")
    oncall_ok = False
    try:
        relay.post_channel(settings.oncall_channel, event)
        oncall_ok = True
    except RelayError as e:
        errors.append(f"on-call channel: {e}")
    if errors:
        raise EscalationError(f"ticket #{number} escalated but delivery failed — " + "; ".join(errors))
    return EscalationResult(tenant=tenant.slug, number=number, status="escalated", delivered=True, delivery_id=delivery_id, oncall_delivered=oncall_ok)
