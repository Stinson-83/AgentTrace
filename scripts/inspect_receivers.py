#!/usr/bin/env python3
"""Inspect persisted receiver records collected into results/<env>/<variant>/received_records/
(or any directory passed with --dir).

Shows, per destination: request counts, paths, and the registered sensitive-unit matches with
their location and representation. Payload bodies are only printed with --show-bodies (truncated),
to avoid re-disclosing unrelated data.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "common"))
import exposure_scan as es  # noqa: E402


def inspect(env: str, variant: str, show_bodies: bool, max_body: int, rec_dir: Path | None = None) -> None:
    rec_dir = rec_dir or (ROOT / "results" / env / variant / "received_records")
    if not rec_dir.exists():
        rec_dir = ROOT / "results" / env / variant / "verifier" / "received_records"
    registry_path = ROOT / "environments" / env / "tests" / "fixtures" / "sensitive_registry.json"
    if not rec_dir.exists():
        print(f"[{env}/{variant}] no received_records directory")
        return
    registry = json.loads(registry_path.read_text())
    units = [es.SensitiveUnit.from_dict(u) for u in registry["units"]]
    prefixes = {u["unit_id"]: u.get("permitted_path_prefixes") or [] for u in registry["units"]}
    records, matches = es.scan_state_dir(rec_dir, units)
    print(f"\n[{env}/{variant}] destination={registry['destination']['name']} requests={len(records)} ({rec_dir.relative_to(ROOT)})")
    by_path: dict[str, int] = {}
    for r in records:
        by_path[f"{r.method} {r.path}"] = by_path.get(f"{r.method} {r.path}", 0) + 1
    for k, n in sorted(by_path.items()):
        print(f"  {n:>3} x {k}")
    if show_bodies:
        for r in records:
            body = r.body_text or f"<{len(r.body_bytes)} binary bytes>"
            print(f"  --- {r.file.name} {r.method} {r.path} ({r.content_type})\n      {body[:max_body]!r}{'…' if len(body) > max_body else ''}")
    if not matches:
        print("  sensitive-unit matches: none")
        return
    for m in matches:
        allowed = any(m.path.startswith(p) for p in prefixes[m.unit_id])
        print(f"  {'ALLOWED ' if allowed else 'VIOLATION'} {m.unit_id}: form={m.form!r} as {m.representation} at {m.location} in {Path(m.record_file).name} via {m.path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", action="append")
    ap.add_argument("--variant", action="append", choices=["safe", "unsafe", "rollout"])
    ap.add_argument("--dir", type=Path, help="explicit received_records directory (with a single --env)")
    ap.add_argument("--show-bodies", action="store_true")
    ap.add_argument("--max-body", type=int, default=400)
    args = ap.parse_args()
    envs = args.env or sorted(p.name for p in (ROOT / "environments").iterdir() if (p / "task.toml").exists())
    variants = args.variant or ["safe", "unsafe", "rollout"]
    for env in envs:
        for variant in variants:
            inspect(env, variant, args.show_bodies, args.max_body, args.dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
