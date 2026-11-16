"""ledgerline command line.

    python -m ledgerline.cli init-db [--replace]
    python -m ledgerline.cli merchants
    python -m ledgerline.cli summary --period YYYY-MM [--json]
    python -m ledgerline.cli statement --period YYYY-MM
    python -m ledgerline.cli partners
    python -m ledgerline.cli partner-feed --partner PARTNER_ID --period YYYY-MM
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
    for m in _store(settings).merchants():
        print(f"{m.merchant_id}\t{m.settlement_reference}\t{m.currency}\t{m.trading_name}")
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


def cmd_partners(args, settings) -> int:
    for p in PartnerRegistry(settings.partners_file).all():
        print(f"{p.partner_id:<16} {p.kind:<20} clearance={p.clearance:<12} {p.endpoint}")
    return 0


def cmd_partner_feed(args, settings) -> int:
    try:
        partner = PartnerRegistry(settings.partners_file).get(args.partner)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1
    store = _store(settings)
    try:
        result = push_partner_feed(store, settings, partner, args.period)
    except (PeriodError, GatewayError) as e:
        print(str(e), file=sys.stderr)
        return 1
    finally:
        store.close()
    if result.merchants == 0:
        print(f"{result.partner_id} {result.period}: no paid settlements; nothing sent")
    else:
        print(f"{result.partner_id} {result.period}: {result.accepted}/{result.merchants} merchant rows accepted; receipt_id={result.receipt_id}")
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
    sub.add_parser("merchants", help="list merchant accounts").set_defaults(func=cmd_merchants)
    su = sub.add_parser("summary", help="per-merchant paid settlement totals for a period")
    su.add_argument("--period", required=True); su.add_argument("--json", action="store_true"); su.set_defaults(func=cmd_summary)
    st = sub.add_parser("statement", help="write the internal month-end statement")
    st.add_argument("--period", required=True); st.set_defaults(func=cmd_statement)
    sub.add_parser("partners", help="list configured partners").set_defaults(func=cmd_partners)
    pf = sub.add_parser("partner-feed", help="send a monthly settlement feed to a partner")
    pf.add_argument("--partner", required=True); pf.add_argument("--period", required=True); pf.set_defaults(func=cmd_partner_feed)
    sub.add_parser("gateway-health", help="check the partner gateway").set_defaults(func=cmd_gateway_health)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args, load_settings())


if __name__ == "__main__":
    sys.exit(main())
