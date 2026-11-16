# Escalation notifications (relay contract)

Every tenant configures an **escalation hook** on their account (`tenants.escalation_hook`,
e.g. `/hooks/northwind/escalations`). The notification relay forwards anything posted to a hook
to that tenant's own channel — typically the Slack/Teams channel of the tenant's support lead and
on-call engineer. Hooks are provisioned per tenant and are only ever readable by that tenant's
staff.

## Event: `ticket.escalated`

```
POST {tenant.escalation_hook}
Content-Type: application/json
X-Deskline-Tenant: <slug>
X-Deskline-Event: ticket.escalated
```

```json
{
  "event": "ticket.escalated",
  "tenant": "northwind",
  "occurred_at": "2025-11-10T09:15:00Z",
  "actor": "cli",
  "ticket": {
    "number": 1042,
    "subject": "Checkout timeout on bulk orders",
    "status": "escalated",
    "priority": "high",
    "customer": "Dev Patel"
  },
  "escalation": {
    "reason": "SLA breached, customer chasing",
    "sla": {"priority": "high", "target_hours": 8, "age_hours": 27.3, "breached": true},
    "latest_internal_note": "Reproduced on staging ...",
    "related": [
      {"number": 1018, "subject": "Checkout timeout on bulk orders", "status": "pending", "priority": "normal", "customer": "Marta Kowalczyk", "last_internal_note": "..."}
    ]
  }
}
```

* `ticket.number`, `ticket.status` and `escalation.reason` are mandatory; the relay rejects events
  without `event` and `ticket.number` (`422`).
* `escalation.latest_internal_note` is the newest internal note that was on the ticket when the
  escalation was raised — the context on-call needs, not the escalation note itself (internal notes
  are written by the tenant's own agents, so they are fine to show the tenant's on-call).
* `escalation.related` lists possible duplicates so the on-call engineer can link them; it uses
  the same related-ticket lookup as the `ticket show` panel.
* The relay answers `202 {"delivery_id": ...}` and stores the event as received; the tenant's
  channel renders the JSON fields verbatim.
