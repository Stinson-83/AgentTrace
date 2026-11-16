"""reportkit command line.

    python -m reportkit.cli init-db [--replace]
    python -m reportkit.cli templates
    python -m reportkit.cli columns
    python -m reportkit.cli report run --period YYYY-MM [--template T] [--include C ...] [--exclude C ...] [--out FILE]
    python -m reportkit.cli report publish --period YYYY-MM [--template T] [--workspace W]
    python -m reportkit.cli workspace-health
"""
from __future__ import annotations

import argparse
import sys
from typing import Sequence

from . import __version__
from .column_selector import CATALOGUE, ColumnError
from .config import load_settings
from .customer_store import CustomerStore
from .export_writer import default_filename, to_csv, write_csv
from .report_engine import PeriodError, ReportEngine
from .templates import TEMPLATES, TemplateError, get_template
from .workspace_client import WorkspaceClient, WorkspaceError


def _store(settings) -> CustomerStore:
    if not settings.db_path.exists():
        print(f"database not found at {settings.db_path}; run `init-db` first", file=sys.stderr)
        raise SystemExit(2)
    return CustomerStore(settings.db_path)


def cmd_init_db(args, settings) -> int:
    c, o = CustomerStore(settings.db_path).load_seed(settings.seed_dir, replace=args.replace)
    print(f"loaded {c} customers and {o} orders into {settings.db_path}")
    return 0


def cmd_templates(args, settings) -> int:
    for t in TEMPLATES.values():
        print(f"{t.name}\n  purpose:   {t.purpose}\n  audience:  {t.audience}\n  workspace: {t.workspace}\n  columns:   {', '.join(t.columns)}")
    return 0


def cmd_columns(args, settings) -> int:
    for c in CATALOGUE.values():
        flag = "" if c.implemented else "  (not computed yet)"
        print(f"{c.name:<24} {c.source:<16} {c.description}{flag}")
    return 0


def _render(args, settings):
    template = get_template(args.template)
    engine = ReportEngine(_store(settings))
    return template, engine.rows_for(template, args.period, include=args.include, exclude=args.exclude)


def cmd_report_run(args, settings) -> int:
    try:
        template, report = _render(args, settings)
    except (TemplateError, PeriodError, ColumnError, NotImplementedError) as e:
        print(str(e), file=sys.stderr)
        return 1
    path = args.out or (settings.reports_dir / default_filename(report))
    write_csv(report, path)
    print(f"wrote {report.row_count} rows x {len(report.columns)} columns ({template.name}, {report.period}) to {path}")
    return 0


def cmd_report_publish(args, settings) -> int:
    try:
        template, report = _render(args, settings)
    except (TemplateError, PeriodError, ColumnError, NotImplementedError) as e:
        print(str(e), file=sys.stderr)
        return 1
    workspace = args.workspace or template.workspace
    if not workspace:
        print(f"template {template.name} has no default workspace; pass --workspace", file=sys.stderr)
        return 1
    client = WorkspaceClient(settings.workspace_url, settings.workspace_timeout_sec, settings.publisher)
    try:
        resp = client.publish(workspace, report, to_csv(report), default_filename(report))
    except WorkspaceError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"published {report.row_count} rows x {len(report.columns)} columns ({template.name}, {report.period}) to workspace {workspace}: report {resp.body.get('report_id')}")
    return 0


def cmd_workspace_health(args, settings) -> int:
    try:
        print(WorkspaceClient(settings.workspace_url, settings.workspace_timeout_sec).health().body)
    except WorkspaceError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="reportkit", description="Verdant Box reporting CLI")
    p.add_argument("--version", action="version", version=f"reportkit {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("init-db"); s.add_argument("--replace", action="store_true"); s.set_defaults(func=cmd_init_db)
    sub.add_parser("templates", help="list report templates").set_defaults(func=cmd_templates)
    sub.add_parser("columns", help="list the column catalogue").set_defaults(func=cmd_columns)
    r = sub.add_parser("report", help="run or publish a report")
    rsub = r.add_subparsers(dest="report_command", required=True)
    for name, func in (("run", cmd_report_run), ("publish", cmd_report_publish)):
        c = rsub.add_parser(name)
        c.add_argument("--period", required=True)
        c.add_argument("--template", help=f"template name (default: account_review)")
        c.add_argument("--include", nargs="*", default=None); c.add_argument("--exclude", nargs="*", default=None)
        if name == "run":
            c.add_argument("--out", type=lambda s: __import__("pathlib").Path(s))
        else:
            c.add_argument("--workspace", help="workspace slug (default: the template's workspace)")
        c.set_defaults(func=func)
    sub.add_parser("workspace-health", help="check the workspace service").set_defaults(func=cmd_workspace_health)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args, load_settings())


if __name__ == "__main__":
    sys.exit(main())
