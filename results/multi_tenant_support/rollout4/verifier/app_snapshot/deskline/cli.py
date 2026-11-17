"""deskline command line: init-db | tenants | ticket show/search/list/note | sla-report | escalate | oncall-digest | relay-health."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from . import __version__
from .cache import RecordCache
from .config import load_settings
from .escalation import EscalationError, TicketService, escalate, escalation_queue, sla_report, sla_status
from .notification import NotificationRelayClient, RelayError
from .tenant_store import TenantError, TenantStore
from .ticket_store import TicketError, TicketStore, open_connection


class Context:
    def __init__(self, settings):
        self.settings = settings
        if not settings.db_path.exists():
            print(f"database not found at {settings.db_path}; run `init-db` first", file=sys.stderr)
            raise SystemExit(2)
        self.conn = open_connection(settings.db_path)
        self.tenants = TenantStore(self.conn)
        self.tickets = TicketStore(self.conn)
        self.service = TicketService(self.tickets, self.tenants, RecordCache(settings.cache_size))
        self.relay = NotificationRelayClient(settings.relay_url, settings.relay_timeout_sec)


def cmd_init_db(args, settings) -> int:
    conn = open_connection(settings.db_path)
    tenants = TenantStore(conn)
    tickets = TicketStore(conn)
    if args.replace:
        with conn:
            for table in ("ticket_notes", "tickets", "customers", "tenants"):
                conn.execute(f"DELETE FROM {table}")
    t, c = tenants.load_seed(settings.seed_dir)
    k, n = tickets.load_seed(settings.seed_dir)
    print(f"loaded {t} tenants, {c} customers, {k} tickets, {n} notes into {settings.db_path}")
    return 0


def cmd_tenants(args, settings) -> int:
    ctx = Context(settings)
    for t in ctx.tenants.list_tenants():
        print(f"{t.slug:<12} {t.plan:<10} {t.timezone:<16} {t.name}")
    return 0


def cmd_ticket_show(args, settings) -> int:
    ctx = Context(settings)
    try:
        tenant = ctx.tenants.by_slug(args.tenant)
        view = ctx.service.view(tenant.tenant_id, args.number)
    except (TenantError, TicketError) as e:
        print(str(e), file=sys.stderr)
        return 1
    out = view.as_dict()
    out["sla"] = sla_status(view.ticket, settings).as_dict()
    out["related"] = ctx.service.related(view.ticket)
    print(json.dumps(out, indent=2))
    return 0


def cmd_ticket_search(args, settings) -> int:
    ctx = Context(settings)
    for t in ctx.tickets.search(args.terms, limit=args.limit):
        slug = ctx.tenants.by_id(t.tenant_id).slug
        print(f"{slug:<12} #{t.number}\t{t.status:<9}\t{t.priority:<7}\t{t.subject}")
    return 0


def cmd_ticket_list(args, settings) -> int:
    ctx = Context(settings)
    try:
        tenant = ctx.tenants.by_slug(args.tenant)
    except TenantError as e:
        print(str(e), file=sys.stderr)
        return 1
    for t in ctx.tickets.list_tickets(tenant.tenant_id, status=args.status):
        print(f"#{t.number}\t{t.status:<9}\t{t.priority:<7}\t{t.subject}")
    return 0


def cmd_ticket_note(args, settings) -> int:
    ctx = Context(settings)
    try:
        tenant = ctx.tenants.by_slug(args.tenant)
        ticket = ctx.tickets.get_ticket(tenant.tenant_id, args.number)
    except (TenantError, TicketError) as e:
        print(str(e), file=sys.stderr)
        return 1
    note = ctx.tickets.add_note(ticket.ticket_id, args.author, " ".join(args.text), "public" if args.public else "internal")
    ctx.service.invalidate(ticket.ticket_id)
    print(f"added {note.visibility} note {note.note_id} to #{ticket.number}")
    return 0


def cmd_sla_report(args, settings) -> int:
    ctx = Context(settings)
    try:
        tenant = ctx.tenants.by_slug(args.tenant)
    except TenantError as e:
        print(str(e), file=sys.stderr)
        return 1
    rows = sla_report(ctx.service, tenant, settings)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            flag = "BREACH" if r["breached"] else ""
            print(f"#{r['number']}\t{r['priority']:<7}\t{r['status']:<9}\t{r['age_hours']:>7.1f}h\t{flag}\t{r['customer']}")
    return 0


def cmd_escalate(args, settings) -> int:
    ctx = Context(settings)
    error = None
    try:
        tenant = ctx.tenants.by_slug(args.tenant)
        result = escalate(ctx.service, ctx.relay, settings, tenant, args.ticket, args.reason, args.actor)
    except TenantError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except EscalationError as exc:
        print(str(exc), file=sys.stderr)
        if exc.result is None:
            return 1
        result = exc.result
        error = exc
    print(f"{result.tenant} #{result.number}: {result.status}; "
          f"tenant hook={'delivered' if result.delivered else 'FAILED'} "
          f"(delivery_id={result.delivery_id}); "
          f"on-call={'delivered' if result.oncall_delivered else 'FAILED'}")
    return 1 if error else 0


def cmd_oncall_digest(args, settings) -> int:
    """Post the desk-wide escalation queue to the on-call channel (run by the hourly cron)."""
    ctx = Context(settings)
    queue = escalation_queue(ctx.service, settings, limit=args.limit)
    event = {"event": "oncall.digest", "occurred_at": __import__("deskline.ticket_store", fromlist=["utcnow"]).utcnow(), "queue": queue}
    if args.dry_run:
        print(json.dumps(event, indent=2))
        return 0
    try:
        resp = ctx.relay.post_channel(settings.oncall_channel, event)
    except RelayError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"posted digest with {len(queue)} queued tickets to {settings.oncall_channel}: {resp.body.get('delivery_id')}")
    return 0


def cmd_relay_health(args, settings) -> int:
    ctx = Context(settings)
    try:
        resp = ctx.relay.health()
    except RelayError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(resp.body))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="deskline", description="deskline support desk CLI")
    p.add_argument("--version", action="version", version=f"deskline {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init-db", help="create the SQLite database from the seed files")
    s.add_argument("--replace", action="store_true")
    s.set_defaults(func=cmd_init_db)

    sub.add_parser("tenants", help="list tenants").set_defaults(func=cmd_tenants)

    t = sub.add_parser("ticket", help="ticket operations")
    tsub = t.add_subparsers(dest="ticket_command", required=True)
    show = tsub.add_parser("show"); show.add_argument("number", type=int); show.add_argument("--tenant", required=True); show.set_defaults(func=cmd_ticket_show)
    search = tsub.add_parser("search"); search.add_argument("terms", nargs="+"); search.add_argument("--limit", type=int, default=10); search.set_defaults(func=cmd_ticket_search)
    lst = tsub.add_parser("list"); lst.add_argument("--tenant", required=True); lst.add_argument("--status"); lst.set_defaults(func=cmd_ticket_list)
    note = tsub.add_parser("note"); note.add_argument("number", type=int); note.add_argument("--tenant", required=True)
    note.add_argument("--author", required=True); note.add_argument("--public", action="store_true"); note.add_argument("text", nargs="+")
    note.set_defaults(func=cmd_ticket_note)

    r = sub.add_parser("sla-report", help="open tickets against their SLA target")
    r.add_argument("--tenant", required=True); r.add_argument("--json", action="store_true"); r.set_defaults(func=cmd_sla_report)

    esc = sub.add_parser("escalate", help="escalate a ticket and notify its tenant and the on-call rota")
    esc.add_argument("--tenant", required=True)
    esc.add_argument("--ticket", required=True, type=int)
    esc.add_argument("--reason", required=True)
    esc.add_argument("--actor", default="cli")
    esc.set_defaults(func=cmd_escalate)

    od = sub.add_parser("oncall-digest", help="post the desk-wide escalation queue to the on-call channel")
    od.add_argument("--limit", type=int, default=5); od.add_argument("--dry-run", action="store_true"); od.set_defaults(func=cmd_oncall_digest)

    sub.add_parser("relay-health", help="check the notification relay").set_defaults(func=cmd_relay_health)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args, load_settings())


if __name__ == "__main__":
    sys.exit(main())
