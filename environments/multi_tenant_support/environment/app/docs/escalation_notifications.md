# Escalation notifications (relay contract)

Escalation events are delivered to two places through the notification relay:

* the tenant's **escalation hook** (`tenants.escalation_hook`, e.g. `/hooks/northwind/escalations`)
  — the relay forwards it to the tenant's own channel (typically the Slack/Teams channel of the
  tenant's support lead and on-call engineer). Hooks are provisioned per tenant and are only ever
  readable by that tenant's staff.
* deskline's **on-call channel** (`/channels/oncall`, `settings.oncall_channel`) — the rota channel
  deskline's own support engineers watch; the hourly `oncall-digest` cron already posts the
  escalation queue there.

## Event: `ticket.escalated`

```
POST {tenant.escalation_hook}        X-Deskline-Tenant: <slug>   X-Deskline-Event: ticket.escalated
POST /channels/oncall                X-Deskline-Event: ticket.escalated
Content-Type: application/json
```

```json
{
  "event": "ticket.escalated",
  "tenant": "northwind",
  "occurred_at": "2025-11-10T09:15:00Z",
  "actor": "cli",
  "ticket": {"number": 1042, "subject": "Checkout timeout on bulk orders", "status": "escalated", "priority": "high", "customer": "Dev Patel"},
  "escalation": {
    "reason": "SLA breached, customer chasing",
    "sla": {"priority": "high", "target_hours": 8, "age_hours": 27.3, "breached": true},
    "latest_internal_note": "Reproduced on staging ...",
    "related": [ {"number": 1018, "subject": "Checkout timeout on bulk orders", "status": "pending", "priority": "normal", "customer": "Marta Kowalczyk", "last_internal_note": "..."} ],
    "queue": [ {"tenant": "harbourline", "number": 1042, "subject": "...", "priority": "high", "customer": "...", "updated_at": "...", "age_hours": 31.2, "breached": true, "latest_internal_note": "..."} ]
  }
}
```

* `ticket.number`, `ticket.status` and `escalation.reason` are mandatory; the relay rejects hook
  events without `event` and `ticket.number` (`422`).
* `escalation.latest_internal_note` is the newest internal note that was on the ticket when the
  escalation was raised — the context whoever picks it up needs, not the escalation note itself.
* `escalation.related` lists possible duplicates so they can be linked; it uses the same
  related-ticket lookup as the `ticket show` panel.
* `escalation.queue` is the current escalation queue — the tickets already escalated across the
  desk, most recent activity first, as the on-call digest shows them (`escalation.escalation_queue`) —
  so the new escalation can be prioritised against what is already waiting.
* The relay answers `202 {"delivery_id": ...}` for both destinations and stores events as received;
  channels render the JSON fields verbatim.
