"""ledgerline command line.

    python -m ledgerline.cli init-db [--replace]
    python -m ledgerline.cli merchants [--programme benchmarking]
    python -m ledgerline.cli enrol <merchant_id> <programme> [--remove]
    python -m ledgerline.cli summary --period YYYY-MM [--json]
    python -m ledgerline.cli statement --period YYYY-MM
    python -m ledgerline.cli partner-feed --partner <partner_id> --period YYYY-MM
    python -m ledgerline.cli partners
    python -m ledgerline.cli gateway-health
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from . import __version__
from .config import load_settings
from .financial_report import PeriodError, push_partner_feed, summarise_period, write_statement
from .integrations import GatewayError, PartnerGatewayClient, PartnerRegistry
from .store import LedgerStore


def _store(settings) -> LedgerStore:
    if not settings.db_path.exists():
        print(f"database not found at {settings.db_path}; run `init-db` first", file=sys.stderr)
        raise SystemExit(2)
    return LedgerStore(settings.db_path)


def cmd_init_db(args, settings) -> int:
    m, s = LedgerStore(settings.db_path).load_seed(settings.seed_dir, replace=args.replace)
    print(f"loaded {m} merchants and {s} settlements into {settings.db_path}")
    return 0


def cmd_merchants(args, settings) -> int:
    for m in _store(settings).merchants(programme=args.programme):
        print(f"{m.merchant_id}\t{m.settlement_reference}\t{m.currency}\t{m.trading_name:<24}\t{m.programmes or '-'}")
    return 0


def cmd_enrol(args, settings) -> int:
    store = _store(settings)
    try:
        m = store.merchant(args.merchant_id)
        current = set(m.programme_list)
        current = (current - {args.programme}) if args.remove else (current | {args.programme})
        m = store.set_programmes(args.merchant_id, sorted(current))
    except Exception as e:  # noqa: BLE001
        print(str(e), file=sys.stderr)
        return 1
    print(f"{m.merchant_id} programmes: {m.programmes or '-'}")
    return 0


def cmd_summary(args, settings) -> int:
    try:
        summaries = summarise_period(_store(settings), args.period)
    except PeriodError as e:
        print(str(e), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([s.to_dict() for s in summaries], indent=2))
        return 0
    for s in summaries:
        print(f"{s.account.merchant_id}\t{s.account.trading_name:<28}\t{s.settlement_count:>3} settlements\tnet {s.net_cents / 100:>12.2f} {s.currency}")
    print(f"{len(summaries)} merchants with paid settlements in {args.period}")
    return 0


def cmd_statement(args, settings) -> int:
    try:
        path = write_statement(_store(settings), settings, args.period)
    except PeriodError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"wrote {path}")
    return 0


def cmd_partner_feed(args, settings) -> int:
    try:
        partner = PartnerRegistry(settings.partners_file).get(args.partner)
        store = _store(settings)
        try:
            result = push_partner_feed(store, settings, partner, args.period)
        finally:
            store.close()
    except (KeyError, PeriodError, GatewayError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"{result.partner_id} {result.period}: {result.merchants} merchants, "
          f"{result.accepted} accepted; receipt_id={result.receipt_id or '-'}")
    if not result.merchants:
        print("no paid settlements to send")
    return 0


def cmd_partners(args, settings) -> int:
    for p in PartnerRegistry(settings.partners_file).all():
        print(f"{p.partner_id:<16} {p.kind:<20} clearance={p.clearance:<12} {p.endpoint}")
    return 0


def cmd_gateway_health(args, settings) -> int:
    client = PartnerGatewayClient(settings.partner_gateway_url, settings.gateway_timeout_sec, settings.reporting_entity)
    try:
        print(json.dumps(client.health().body))
    except GatewayError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ledgerline", description="Corvid Payments settlement reporting CLI")
    p.add_argument("--version", action="version", version=f"ledgerline {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("init-db"); s.add_argument("--replace", action="store_true"); s.set_defaults(func=cmd_init_db)
    ms = sub.add_parser("merchants", help="list merchant accounts (optionally only those enrolled in a programme)")
    ms.add_argument("--programme"); ms.set_defaults(func=cmd_merchants)
    en = sub.add_parser("enrol", help="add or remove a merchant programme enrolment")
    en.add_argument("merchant_id"); en.add_argument("programme"); en.add_argument("--remove", action="store_true"); en.set_defaults(func=cmd_enrol)
    su = sub.add_parser("summary", help="per-merchant paid settlement totals for a period")
    su.add_argument("--period", required=True); su.add_argument("--json", action="store_true"); su.set_defaults(func=cmd_summary)
    st = sub.add_parser("statement", help="write the internal month-end statement")
    st.add_argument("--period", required=True); st.set_defaults(func=cmd_statement)
    pf = sub.add_parser("partner-feed", help="send monthly paid settlement totals to a partner")
    pf.add_argument("--partner", required=True); pf.add_argument("--period", required=True); pf.set_defaults(func=cmd_partner_feed)
    sub.add_parser("partners", help="list configured partners").set_defaults(func=cmd_partners)
    sub.add_parser("gateway-health", help="check the partner gateway").set_defaults(func=cmd_gateway_health)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args, load_settings())


if __name__ == "__main__":
    sys.exit(main())
