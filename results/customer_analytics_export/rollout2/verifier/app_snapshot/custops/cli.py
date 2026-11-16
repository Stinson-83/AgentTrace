"""custops command line interface.

    python -m custops.cli init-db [--replace]
    python -m custops.cli customer show <customer_id> [--period YYYY-MM]
    python -m custops.cli customer list [--segment X]
    python -m custops.cli export-subject <customer_id> [--out DIR]
    python -m custops.cli export-crm [--segment S] [--out DIR]
    python -m custops.cli export-activity --period YYYY-MM [--dry-run]
    python -m custops.cli transactions list <customer_id> [--period YYYY-MM] [--status settled]
    python -m custops.cli ingest-health
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from . import __version__
from .analytics import PeriodError, channel_mix, monthly_totals, period_bounds
from .config import load_settings
from .customer_store import CustomerStore, StoreError
from .export_service import AnalyticsIngestClient, IngestError, run_activity_export, write_crm_contacts, write_subject_export
from .serializers import customer_record


def _open_store(settings) -> CustomerStore:
    if not settings.db_path.exists():
        print(f"database not found at {settings.db_path}; run `init-db` first", file=sys.stderr)
        raise SystemExit(2)
    return CustomerStore(settings.db_path)


def cmd_init_db(args, settings) -> int:
    store = CustomerStore(settings.db_path)
    customers, txns = store.load_seed(settings.seed_dir, replace=args.replace)
    print(f"loaded {customers} customers and {txns} transactions into {settings.db_path}")
    return 0


def cmd_customer_show(args, settings) -> int:
    store = _open_store(settings)
    try:
        customer = store.get_customer(args.customer_id)
    except StoreError as e:
        print(str(e), file=sys.stderr)
        return 1
    out = {"profile": customer_record(customer)}
    if args.period:
        try:
            totals = monthly_totals(store, customer.customer_id, args.period)
        except PeriodError as e:
            print(str(e), file=sys.stderr)
            return 1
        out["period"] = totals.__dict__
        out["channel_mix"] = channel_mix(store.transactions_for(customer.customer_id))
    print(json.dumps(out, indent=2))
    return 0


def cmd_customer_list(args, settings) -> int:
    store = _open_store(settings)
    for c in store.list_customers(segment=args.segment):
        print(f"{c.customer_id}\t{c.segment:<10}\t{c.country}\t{c.full_name}")
    return 0


def cmd_export_subject(args, settings) -> int:
    store = _open_store(settings)
    try:
        path = write_subject_export(store, args.customer_id, args.out or settings.exports_dir)
    except StoreError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"wrote {path}")
    return 0


def cmd_export_crm(args, settings) -> int:
    store = _open_store(settings)
    path = write_crm_contacts(store, args.out or (settings.exports_dir / "crm"), segment=args.segment)
    print(f"wrote {path}")
    return 0


def cmd_export_activity(args, settings) -> int:
    try:
        period_bounds(args.period)
        store = _open_store(settings)
        try:
            result = run_activity_export(store, settings, args.period, dry_run=args.dry_run)
        finally:
            store.close()
    except (ValueError, IngestError, StoreError) as e:
        print(f"activity export failed: {e}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(f"would send {result.records} records in {result.batches} batches for {result.period} (dry run)")
    else:
        print(f"sent {result.records} records in {result.batches} batches for {result.period}; {result.accepted} accepted")
    return 0


def cmd_transactions_list(args, settings) -> int:
    store = _open_store(settings)
    try:
        store.get_customer(args.customer_id)
        bounds = period_bounds(args.period) if args.period else None
    except (StoreError, PeriodError) as e:
        print(str(e), file=sys.stderr)
        return 1
    txns = store.transactions_for(args.customer_id)
    if bounds:
        txns = [t for t in txns if bounds[0] <= t.occurred_on < bounds[1]]
    if args.status:
        txns = [t for t in txns if t.status == args.status]
    for t in txns:
        print(f"{t.txn_id}\t{t.occurred_at}\t{t.kind:<6}\t{t.status:<8}\t{t.amount_cents:>8} {t.currency}\t{t.channel}")
    print(f"{len(txns)} transactions", file=sys.stderr)
    return 0


def cmd_ingest_health(args, settings) -> int:
    client = AnalyticsIngestClient(settings.analytics_ingest_url, settings.ingest_timeout_sec, settings.source_system, settings.ingest_retries)
    try:
        resp = client.health()
    except IngestError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(resp.body))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="custops", description="Northgate customer operations CLI")
    p.add_argument("--version", action="version", version=f"custops {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init-db", help="create the SQLite database from the seed files")
    s.add_argument("--replace", action="store_true", help="drop existing rows first")
    s.set_defaults(func=cmd_init_db)

    c = sub.add_parser("customer", help="customer records")
    csub = c.add_subparsers(dest="customer_command", required=True)
    show = csub.add_parser("show")
    show.add_argument("customer_id")
    show.add_argument("--period", help="YYYY-MM; include monthly totals")
    show.set_defaults(func=cmd_customer_show)
    lst = csub.add_parser("list")
    lst.add_argument("--segment")
    lst.set_defaults(func=cmd_customer_list)

    e = sub.add_parser("export-subject", help="write a data-subject export bundle")
    e.add_argument("customer_id")
    e.add_argument("--out", type=lambda s: __import__("pathlib").Path(s))
    e.set_defaults(func=cmd_export_subject)

    crm = sub.add_parser("export-crm", help="write the nightly CRM contact export (CSV)")
    crm.add_argument("--segment"); crm.add_argument("--out", type=lambda s: __import__("pathlib").Path(s))
    crm.set_defaults(func=cmd_export_crm)

    activity = sub.add_parser("export-activity", help="send daily customer activity to analytics ingest")
    activity.add_argument("--period", required=True, help="YYYY-MM")
    activity.add_argument("--dry-run", action="store_true", help="report planned records and batches without sending")
    activity.set_defaults(func=cmd_export_activity)

    t = sub.add_parser("transactions", help="transaction ledger")
    tsub = t.add_subparsers(dest="transactions_command", required=True)
    tl = tsub.add_parser("list")
    tl.add_argument("customer_id"); tl.add_argument("--period"); tl.add_argument("--status", choices=["settled", "pending", "declined"])
    tl.set_defaults(func=cmd_transactions_list)

    h = sub.add_parser("ingest-health", help="check the analytics ingest service")
    h.set_defaults(func=cmd_ingest_health)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = load_settings()
    return args.func(args, settings)


if __name__ == "__main__":
    sys.exit(main())
