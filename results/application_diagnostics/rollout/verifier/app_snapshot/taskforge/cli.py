"""taskforge command line.

    python -m taskforge.cli init-db [--replace]
    python -m taskforge.cli jobs list [--status S] [--queue Q]
    python -m taskforge.cli jobs show <job_id> [--json]
    python -m taskforge.cli jobs retry <job_id> [--keep-attempts]
    python -m taskforge.cli jobs stats [--json]
    python -m taskforge.cli run-queue [--queue Q] [--max N]
    python -m taskforge.cli observe-health
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from . import __version__
from .config import load_settings
from .job_store import JobStore
from .observability_client import ObservabilityClient, ObserveError
from .runner import run_queue


def _store(settings) -> JobStore:
    if not settings.db_path.exists():
        print(f"database not found at {settings.db_path}; run `init-db` first", file=sys.stderr)
        raise SystemExit(2)
    return JobStore(settings.db_path)


def cmd_init_db(args, settings) -> int:
    n = JobStore(settings.db_path).load_seed(settings.seed_dir, replace=args.replace)
    print(f"loaded {n} jobs into {settings.db_path}")
    return 0


def cmd_jobs_list(args, settings) -> int:
    store = _store(settings)
    for j in store.list(status=args.status, queue=args.queue):
        err = f"\t{j.last_error_type}" if j.last_error_type else ""
        print(f"{j.job_id}\t{j.job_type:<16}\t{j.queue:<8}\t{j.status:<9}\t{j.attempts}/{j.max_attempts}{err}")
    print(json.dumps(store.counts()), file=sys.stderr)
    return 0


def cmd_jobs_show(args, settings) -> int:
    store = _store(settings)
    try:
        job = store.get(args.job_id)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(job.to_dict(), indent=2))
    else:
        print(f"{job.job_id} {job.job_type} [{job.status}] attempts={job.attempts}/{job.max_attempts} queue={job.queue}")
        print(f"  request {job.context.request_id} {job.context.method} {job.context.route} account={job.context.account_id}")
        if job.last_error_type:
            print(f"  last error: {job.last_error_type}: {job.last_error_message}")
    return 0


def cmd_jobs_stats(args, settings) -> int:
    store = _store(settings)
    stats = {"counts": store.counts(), "dead": store.failure_breakdown()}
    if args.json:
        print(json.dumps(stats, indent=2))
        return 0
    for status, n in stats["counts"].items():
        print(f"{status:<10} {n}")
    for error_type, n in stats["dead"]["by_error_type"].items():
        print(f"  dead/{error_type:<24} {n}")
    return 0


def cmd_jobs_retry(args, settings) -> int:
    store = _store(settings)
    try:
        job = store.requeue(args.job_id, reset_attempts=not args.keep_attempts)
    except (KeyError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"{job.job_id} requeued (attempts={job.attempts}/{job.max_attempts})")
    return 0


def cmd_run_queue(args, settings) -> int:
    store = _store(settings)
    summary = run_queue(store, settings, queue=args.queue, max_jobs=args.max)
    print(json.dumps(summary.as_dict(), indent=2))
    return 0 if not summary.diagnostics_errors else 3


def cmd_observe_health(args, settings) -> int:
    client = ObservabilityClient(settings.observe_url, settings.observe_timeout_sec, settings.service_name)
    try:
        resp = client.health()
    except ObserveError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(resp.body))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="taskforge", description="taskforge job runner CLI")
    p.add_argument("--version", action="version", version=f"taskforge {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init-db", help="create the SQLite job store from the seed file")
    s.add_argument("--replace", action="store_true"); s.set_defaults(func=cmd_init_db)

    j = sub.add_parser("jobs", help="inspect jobs")
    jsub = j.add_subparsers(dest="jobs_command", required=True)
    lst = jsub.add_parser("list"); lst.add_argument("--status"); lst.add_argument("--queue"); lst.set_defaults(func=cmd_jobs_list)
    show = jsub.add_parser("show"); show.add_argument("job_id"); show.add_argument("--json", action="store_true"); show.set_defaults(func=cmd_jobs_show)
    stats = jsub.add_parser("stats"); stats.add_argument("--json", action="store_true"); stats.set_defaults(func=cmd_jobs_stats)
    retry = jsub.add_parser("retry"); retry.add_argument("job_id"); retry.add_argument("--keep-attempts", action="store_true"); retry.set_defaults(func=cmd_jobs_retry)

    r = sub.add_parser("run-queue", help="process pending jobs")
    r.add_argument("--queue"); r.add_argument("--max", type=int); r.set_defaults(func=cmd_run_queue)

    sub.add_parser("observe-health", help="check the observability service").set_defaults(func=cmd_observe_health)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args, load_settings())


if __name__ == "__main__":
    sys.exit(main())
