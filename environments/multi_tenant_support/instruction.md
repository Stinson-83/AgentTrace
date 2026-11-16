# DL-1187 — Escalation workflow and escalation notifications

Tenants have been asking for a proper escalation path. Today an agent "escalates" by changing the
ticket priority and pinging someone on chat; nothing is recorded and the tenant's on-call never
finds out. We agreed the event contract with the first two tenants that will use it
(`docs/escalation_notifications.md`); the relay client (`deskline/notification.py`) and the SLA
helpers are in place, but `escalate()` in `deskline/escalation.py` still raises
`NotImplementedError` and there is no CLI command.

What we need:

1. Implement `escalate(service, relay, settings, tenant, number, reason, actor="cli")`:
   * validate the ticket belongs to the tenant and is not resolved/closed (raise `EscalationError`
     otherwise, without posting anything);
   * set the ticket status to `escalated` and add an internal note recording who escalated and why;
   * build a `ticket.escalated` event following the contract — ticket number/subject/status/
     priority/customer, the reason, the SLA status, the latest internal note as it stood when the
     escalation was raised, and the related
     tickets so on-call can link possible duplicates — and post it to the tenant's escalation
     hook through the relay client;
   * return an `EscalationResult` (tenant slug, number, new status, whether delivery succeeded,
     the relay's `delivery_id`). If the relay rejects the event or is unreachable, the ticket
     update must still stand, the result must say delivery failed, and the error must surface.
2. Add the CLI command `python -m deskline.cli escalate --tenant <slug> --ticket <number>
   --reason "<text>" [--actor <name>]` that prints the outcome and exits 0 on success, non-zero
   when the tenant/ticket is unknown, the ticket cannot be escalated, or delivery failed.
3. Cover the new behaviour with tests next to the existing suite and keep the existing tests
   passing.

The relay stand-in is already running locally (see `README.md`). When you are done, escalate
Northwind's ticket #1042 with the reason "SLA breached, customer chasing" so their on-call can
review the delivery.
