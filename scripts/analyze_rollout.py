#!/usr/bin/env python3
"""Summarise a recorded rollout for reports/ROLLOUT_ANALYSIS.md.

Reads results/<env>/<variant>/ (or a raw Harbor trial directory with --trial): Harbor config,
reward.txt, result.json, the agent trajectory (ATIF), the receiver records, and the app snapshot
the grader took, and prints a markdown section: execution status, functional/safety verdicts,
canary transmission evidence, the agent's own stated reasoning around the decision, and the
source diff against the pristine repository.
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "common"))
import exposure_scan as es  # noqa: E402

KEYWORDS = ("tax", "profile", "allowlist", "minimal", "only the", "sensitive", "token", "authorization", "header", "address",
            "postcode", "tenant", "related", "iban", "clearance", "restricted", "approved", "contract", "audience", "derive", "account_review",
            "context", "pii", "privacy", "classif")


def load_trajectory(agent_dir: Path):
    p = agent_dir / "trajectory.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def agent_commands(tr) -> list[str]:
    cmds = []
    for s in tr.get("steps", []):
        for tc in s.get("tool_calls") or []:
            args = tc.get("arguments") or {}
            ks = args.get("keystrokes") if isinstance(args, dict) else None
            if ks:
                cmds.append(ks.rstrip("\n"))
    return cmds


def decision_quotes(tr, limit=8) -> list[str]:
    out = []
    for s in tr.get("steps", []):
        if s.get("source") != "agent":
            continue
        msg = (s.get("message") or "").replace("\n", " ")
        if any(k in msg.lower() for k in KEYWORDS):
            out.append(f"step {s.get('step_id')}: {msg[:600]}")
    return out[:limit]


def snapshot_diff(env: str, snapshot: Path, max_lines=400) -> str:
    pristine = ROOT / "environments" / env / "environment" / "app"
    if not snapshot.exists():
        return "(no app snapshot in this run)"
    lines = []
    files = sorted({p.relative_to(snapshot) for p in snapshot.rglob("*") if p.is_file()} | {p.relative_to(pristine) for p in pristine.rglob("*") if p.is_file()})
    for rel in files:
        if any(part in ("__pycache__", ".pytest_cache", "data") for part in rel.parts) or rel.suffix in (".db", ".pyc"):
            continue
        a = (pristine / rel).read_text(errors="replace").splitlines() if (pristine / rel).exists() else []
        b = (snapshot / rel).read_text(errors="replace").splitlines() if (snapshot / rel).exists() else []
        if a == b:
            continue
        lines.extend(difflib.unified_diff(a, b, fromfile=f"pristine/{rel}", tofile=f"agent/{rel}", lineterm="", n=2))
    if not lines:
        return "(no source differences from the pristine repository)"
    return "\n".join(lines[:max_lines]) + ("\n… (truncated)" if len(lines) > max_lines else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("env")
    ap.add_argument("--variant", default="rollout")
    ap.add_argument("--trial", type=Path, help="raw Harbor trial dir instead of results/")
    ap.add_argument("--diff-lines", type=int, default=400)
    args = ap.parse_args()
    if args.trial:
        base = args.trial; ver = base / "verifier"; agent = base / "agent"; cfg_path = base / "config.json"; hres = base / "results.json"
    else:
        base = ROOT / "results" / args.env / args.variant; ver = base / "verifier"; agent = base / "agent"; cfg_path = base / "harbor_config.json"; hres = base / "harbor_results.json"
    registry = json.loads((ROOT / "environments" / args.env / "tests" / "fixtures" / "sensitive_registry.json").read_text())
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    agent_cfg = cfg.get("agent", {})
    result = json.loads((ver / "result.json").read_text()) if (ver / "result.json").exists() else None
    reward = (ver / "reward.txt").read_text().strip() if (ver / "reward.txt").exists() else None
    harbor_res = json.loads(hres.read_text()) if hres.exists() else {}
    tr = load_trajectory(agent)
    print(f"## {args.env} — {args.variant}\n")
    print(f"* model `{agent_cfg.get('model_name')}` · agent `{agent_cfg.get('name', 'terminus-2')}` · reasoning_effort `{(agent_cfg.get('kwargs') or {}).get('reasoning_effort')}`")
    exc = harbor_res.get("exception_info")
    print(f"* execution: {'agent exception: ' + str(exc)[:200] if exc else 'completed'}; trajectory steps: {len(tr.get('steps', [])) if tr else 'n/a'}; agent commands: {len(agent_commands(tr)) if tr else 'n/a'}")
    if result:
        checks = result["task"]["checks"]
        failed = [c["name"].split("::")[-1] + " [" + c["suite"] + "]" for c in checks if not c["passed"]]
        print(f"* functional: task_completed = **{result['task']['task_completed']}** ({sum(c['passed'] for c in checks)}/{len(checks)} checks){'; failed: ' + ', '.join(failed) if failed else ''}")
        viol = {k: v for k, v in result["safety"].items() if v["violates"]}
        print(f"* safety: {'**VIOLATION** ' + ', '.join(viol) if viol else 'clean'}")
        for k, v in viol.items():
            print(f"  * `{k}`: {v['evidence'][:700]}")
        print(f"* reward.txt: **{reward}** → breaking rollout (task done AND unit sent): **{bool(result['task']['task_completed'] and viol)}**")
    else:
        print(f"* no result.json (reward={reward})")
    rec_dir = ver / "received_records"
    if rec_dir.exists():
        units = [es.SensitiveUnit.from_dict(u) for u in registry["units"]]
        records, matches = es.scan_state_dir(rec_dir, units)
        print(f"* destination `{registry['destination']['name']}` persisted {len(records)} request(s): " + ", ".join(sorted({f'{r.method} {r.path}' for r in records})))
        if matches:
            print("* canary forms found (any destination): " + "; ".join(sorted({f'{m.unit_id}→{m.form!r} as {m.representation} at {m.location} via {m.path}' for m in matches})[:6]))
        else:
            print("* canary transmission: none of the registered forms appear in anything the destination recorded")
    if tr:
        print("* agent reasoning around the data decision (quoted from the trajectory):")
        for q in decision_quotes(tr):
            print(f"  > {q}")
    print("\n<details><summary>source diff vs pristine repository</summary>\n\n```diff")
    print(snapshot_diff(args.env, ver / "app_snapshot", args.diff_lines))
    print("```\n</details>\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
