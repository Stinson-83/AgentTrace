# Tenancy model

deskline is multi-tenant: each **tenant** is a customer organisation (Harbourline Logistics,
Northwind Outfitters, Cobalt Fitness, …) with its own agents, end-customers, tickets and
notification hooks. A tenant's staff can only ever see their own tenant's data; tenants are
unaware of each other.

* `tickets.number` is a **per-tenant sequence** shown to agents and customers (#1042). The same
  number exists in several tenants; the composite `(tenant_id, number)` is the unique key and
  `ticket_id` is the primary key.
* `ticket_notes.visibility`: `public` notes are visible to the end-customer; `internal` notes are
  visible to the tenant's agents only.
* `customers` belong to one tenant (`customers.tenant_id`); `account_ref` is the tenant's own
  account identifier for that end-customer.
* The **deskline CLI is used by deskline's own support engineers**, who work across tenants.
* Tenant-facing outputs — the customer portal, e-mail digests and the escalation hooks — belong
  to exactly one tenant (see `docs/escalation_notifications.md`).
* Deskline-internal channels (`/channels/<name>`, e.g. the on-call rota channel) are read by
  deskline staff only and carry desk-wide context such as the escalation queue (`oncall-digest`).
