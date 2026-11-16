#!/usr/bin/env python3
"""Run every environment's safe and unsafe reference through the unchanged Harbor harness.

Safe:   harbor run -p environments -i <env> -a oracle  (oracle executes solution/solve.sh)
Unsafe: a temporary copy of environments/<env> whose solution/ is replaced by unsafe_reference/,
        run the same way. Task files, Dockerfile, tests and grader are byte-identical.

Outputs: jobs/<env>/{safe,unsafe}/ (Harbor job dirs) and results/<env>/{safe,unsafe}/ with
reward.txt, result.json and logs copied from the trial.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENVS = ROOT / "environments"
JOBS = ROOT / "jobs"
RESULTS = ROOT / "results"


def harbor_bin() -> str:
    for cand in (shutil.which("harbor"), Path.home() / ".local" / "bin" / "harbor"):
        if cand and Path(cand).exists():
            return str(cand)
    sys.exit("harbor not found; install with `uv tool install harbor`")


def run_harbor(tasks_dir: Path, task_id: str, jobs_dir: Path, job_name: str, extra: list[str]) -> int:
    if (jobs_dir / job_name).exists():
        shutil.rmtree(jobs_dir / job_name)
    cmd = [harbor_bin(), "run", "-p", str(tasks_dir), "-i", task_id, "-a", "oracle", "-k", "1",
           "-o", str(jobs_dir), "--job-name", job_name, "--yes", "-n", "1", *extra]
    print("+", " ".join(cmd), flush=True)
    log = jobs_dir / f"{job_name}.harbor.log"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    with open(log, "w") as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT, env={**os.environ, "TERM": "dumb"})
    return proc.returncode


def collect(env: str, job_name: str) -> dict:
    job_dir = JOBS / env / job_name
    trials = [p for p in job_dir.iterdir() if p.is_dir()] if job_dir.exists() else []
    dest = RESULTS / env / job_name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    summary = {"env": env, "variant": job_name, "reward": None, "task_completed": None, "violations": None, "trial_dir": None}
    for trial in trials:
        ver = trial / "verifier"
        if not ver.exists():
            continue
        summary["trial_dir"] = str(trial.relative_to(ROOT))
        for name in ("reward.txt", "result.json", "grader.log", "test-stdout.txt", "receiver.log", "pytest_functional.log",
                     "pytest_regression.log", "pytest_security.log", "receiver_manifest.json", "grader_started_at"):
            if (ver / name).exists():
                shutil.copy(ver / name, dest / name)
        if (ver / "received_records").exists():
            shutil.copytree(ver / "received_records", dest / "received_records")
        for name in ("results.json", "trial.log", "config.json"):
            if (trial / name).exists():
                shutil.copy(trial / name, dest / f"harbor_{name}")
        if (trial / "agent").exists():
            shutil.copytree(trial / "agent", dest / "agent_logs", dirs_exist_ok=True)
        if (ver / "reward.txt").exists():
            summary["reward"] = (ver / "reward.txt").read_text().strip()
        if (ver / "result.json").exists():
            r = json.loads((ver / "result.json").read_text())
            summary["task_completed"] = r["task"]["task_completed"]
            summary["violations"] = sorted(k for k, v in r["safety"].items() if v["violates"])
    if (job_dir / "result.json").exists():
        shutil.copy(job_dir / "result.json", dest / "harbor_job_result.json")
    if (JOBS / env / f"{job_name}.harbor.log").exists():
        shutil.copy(JOBS / env / f"{job_name}.harbor.log", dest / "harbor_run.log")
    (dest / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def run_env(env: str, variants: list[str], extra: list[str]) -> list[dict]:
    out = []
    if "safe" in variants:
        rc = run_harbor(ENVS, env, JOBS / env, "safe", extra)
        s = collect(env, "safe"); s["harbor_exit"] = rc; out.append(s)
    if "unsafe" in variants:
        with tempfile.TemporaryDirectory(prefix="harbor-unsafe-") as tmp:
            tasks_dir = Path(tmp) / "environments"
            tasks_dir.mkdir()
            copy = tasks_dir / env
            shutil.copytree(ENVS / env, copy, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            shutil.rmtree(copy / "solution")
            shutil.copytree(copy / "unsafe_reference", copy / "solution")
            rc = run_harbor(tasks_dir, env, JOBS / env, "unsafe", extra)
        s = collect(env, "unsafe"); s["harbor_exit"] = rc; out.append(s)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", action="append", help="environment id (default: all)")
    ap.add_argument("--variant", choices=["safe", "unsafe"], action="append")
    ap.add_argument("--force-build", action="store_true")
    args = ap.parse_args()
    envs = args.env or sorted(p.name for p in ENVS.iterdir() if (p / "task.toml").exists())
    variants = args.variant or ["safe", "unsafe"]
    extra = ["--force-build"] if args.force_build else []
    summaries = []
    for env in envs:
        summaries.extend(run_env(env, variants, extra))
    print("\n== reference runs ==")
    ok = True
    for s in summaries:
        expect = "1" if s["variant"] == "safe" else "0"
        status = "OK" if s["reward"] == expect and (s["variant"] == "safe" or s["violations"]) else "UNEXPECTED"
        ok &= status == "OK"
        print(f"{s['env']:<32} {s['variant']:<7} reward={s['reward']} task_completed={s['task_completed']} violations={s['violations']} [{status}]")
    (RESULTS / "reference_summary.json").write_text(json.dumps(summaries, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
