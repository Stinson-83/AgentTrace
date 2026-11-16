#!/usr/bin/env python3
"""Copy a Harbor rollout job's trial outputs into results/<env>/<dest>/ and print a summary.

Copies: reward.txt, result.json, the verifier directory (grader/pytest logs, received_records),
the agent directory (trajectory, terminal pane/recording), trial.log and Harbor's results.json.
Any occurrence of the OPENAI_API_KEY value is redacted before copying.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def scrub(path: Path) -> None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key or key == "PASTE_YOUR_API_KEY_HERE" or not path.is_file():
        return
    try:
        text = path.read_text()
    except (UnicodeDecodeError, OSError):
        return
    if key in text:
        path.write_text(text.replace(key, "<redacted>"))


def collect(env: str, job_name: str, dest_name: str) -> dict:
    job_dir = ROOT / "jobs" / env / job_name
    dest = ROOT / "results" / env / dest_name
    summary = {"env": env, "job": job_name, "reward": None, "task_completed": None, "violations": None, "trial_dir": None, "agent_error": None}
    if not job_dir.exists():
        summary["error"] = "job directory missing"
        return summary
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for trial in sorted(p for p in job_dir.iterdir() if p.is_dir()):
        summary["trial_dir"] = str(trial.relative_to(ROOT))
        ver = trial / "verifier"
        if ver.exists():
            shutil.copytree(ver, dest / "verifier", dirs_exist_ok=True)
            for name in ("reward.txt", "result.json"):
                if (ver / name).exists():
                    shutil.copy(ver / name, dest / name)
        if (trial / "agent").exists():
            shutil.copytree(trial / "agent", dest / "agent", dirs_exist_ok=True)
        for name in ("results.json", "trial.log", "config.json"):
            if (trial / name).exists():
                shutil.copy(trial / name, dest / f"harbor_{name}")
        if (trial / "results.json").exists():
            r = json.loads((trial / "results.json").read_text())
            info = r.get("exception_info")
            summary["agent_error"] = info.get("exception_type") if isinstance(info, dict) else info
    if (job_dir / "result.json").exists():
        shutil.copy(job_dir / "result.json", dest / "harbor_job_result.json")
    log = ROOT / "jobs" / env / f"{job_name}.harbor.log"
    if log.exists():
        shutil.copy(log, dest / "harbor_run.log")
    for p in dest.rglob("*"):
        scrub(p)
    if (dest / "reward.txt").exists():
        summary["reward"] = (dest / "reward.txt").read_text().strip()
    if (dest / "result.json").exists():
        r = json.loads((dest / "result.json").read_text())
        summary["task_completed"] = r["task"]["task_completed"]
        summary["violations"] = sorted(k for k, v in r["safety"].items() if v["violates"])
    summary["breaking_rollout"] = bool(summary["task_completed"]) and bool(summary["violations"])
    (dest / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("envs", nargs="*")
    ap.add_argument("--job-name", default="rollout")
    ap.add_argument("--dest-name", default=None, help="results subdirectory (default: the job name)")
    args = ap.parse_args()
    envs = args.envs or sorted(p.name for p in (ROOT / "environments").iterdir() if (p / "task.toml").exists())
    for env in envs:
        s = collect(env, args.job_name, args.dest_name or args.job_name)
        print(f"{env:<28} reward={s['reward']} task_completed={s['task_completed']} violations={s['violations']} breaking={s.get('breaking_rollout')} agent_error={s['agent_error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
