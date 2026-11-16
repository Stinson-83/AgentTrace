#!/usr/bin/env python3
"""Validate the project, then build submission.zip (environments, results, docs, scripts, reports)
excluding .env, credentials, caches, temporary files, jobs/ and papers/. Verifies the archive.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ["environments", "results", "scripts", "reports", "common", "README.md", "QUALITY_BAR.md", "ASSIGNMENT_ANALYSIS.md",
           "RESEARCH_TO_DESIGN.md", "HARBOR_IMPLEMENTATION_NOTES.md", "ENVIRONMENT_COMPARISON.md", "PROGRESS.md", ".gitignore"]
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".git", "node_modules"}
EXCLUDE_FILES = {".env", "submission.zip"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".tmp"}
SECRET_RE = re.compile(r"sk-[A-Za-z0-9_-]{20,}")


def iter_files():
    for item in INCLUDE:
        p = ROOT / item
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_dir() or any(part in EXCLUDE_DIRS for part in f.parts):
                    continue
                if f.name in EXCLUDE_FILES or f.suffix in EXCLUDE_SUFFIXES or f.name.endswith(".env"):
                    continue
                yield f


def main() -> int:
    if "--skip-validate" not in sys.argv:
        rc = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_all.py")], cwd=ROOT).returncode
        if rc != 0 and "--force" not in sys.argv:
            print("validation failed; fix the problems or pass --force to package anyway")
            return rc
    out = ROOT / "submission.zip"
    if out.exists():
        out.unlink()
    key = os.environ.get("OPENAI_API_KEY", "")
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in iter_files():
            rel = f.relative_to(ROOT)
            try:
                text = f.read_text()
            except (UnicodeDecodeError, OSError):
                text = None
            if text is not None and ((key and key != "PASTE_YOUR_API_KEY_HERE" and key in text) or SECRET_RE.search(text)):
                print(f"refusing to package {rel}: looks like it contains a credential")
                return 2
            zf.write(f, str(Path("solumn_assignment") / rel))
            n += 1
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert not any(name.endswith("/.env") for name in names), ".env leaked into archive"
        assert zf.testzip() is None, "archive corrupt"
        for required in ("README.md", "QUALITY_BAR.md"):
            assert any(name.endswith(f"solumn_assignment/{required}") for name in names), f"{required} missing"
        envs = {name.split("/")[2] for name in names if name.startswith("solumn_assignment/environments/") and name.count("/") >= 3}
        results = {name.split("/")[2] for name in names if name.startswith("solumn_assignment/results/") and name.count("/") >= 3}
        print(f"packaged {n} files into {out} ({out.stat().st_size / 1e6:.1f} MB); environments={sorted(envs)}; results={sorted(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
