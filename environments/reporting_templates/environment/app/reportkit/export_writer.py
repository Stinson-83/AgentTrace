"""CSV rendering of reports."""
from __future__ import annotations

import csv
import io
from pathlib import Path

from .report_engine import Report


def to_csv(report: Report) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=report.columns, lineterminator="\n")
    writer.writeheader()
    for row in report.rows:
        writer.writerow({c: ("" if row.get(c) is None else row.get(c)) for c in report.columns})
    return buf.getvalue()


def write_csv(report: Report, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_csv(report), encoding="utf-8")
    return path


def default_filename(report: Report) -> str:
    return f"{report.template}-{report.period}.csv"
