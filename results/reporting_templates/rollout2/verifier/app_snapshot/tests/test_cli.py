import csv
import io
from unittest.mock import patch

import pytest

from reportkit.cli import main
from reportkit.templates import get_template
from reportkit.workspace_client import PublishResponse


@pytest.fixture()
def cli_settings(store, tmp_path, monkeypatch):
    from reportkit.config import load_settings

    monkeypatch.setenv("REPORTKIT_DB_PATH", str(tmp_path / "r.db"))
    monkeypatch.setenv("REPORTKIT_REPORTS_DIR", str(tmp_path / "reports"))
    return load_settings()


def test_run_monthly_customer_performance(cli_settings, capsys):
    assert main([
        "report", "run", "--template", "monthly_customer_performance", "--period", "2025-10",
    ]) == 0
    path = cli_settings.reports_dir / "monthly_customer_performance-2025-10.csv"
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == get_template("monthly_customer_performance").columns
        rows = list(reader)
    assert rows and all(r["period"] == "2025-10" for r in rows)
    assert "wrote" in capsys.readouterr().out


def test_publish_monthly_customer_performance_defaults_to_revenue_ops(cli_settings, capsys):
    with patch("reportkit.cli.WorkspaceClient", autospec=True) as client:
        client.return_value.publish.return_value = PublishResponse(201, {"report_id": "rpt_test"})
        assert main([
            "report", "publish", "--template", "monthly_customer_performance", "--period", "2025-10",
        ]) == 0
    client.return_value.publish.assert_called_once()
    workspace, report, text, filename = client.return_value.publish.call_args.args
    assert workspace == "revenue-ops"
    assert report.template == "monthly_customer_performance"
    assert report.period == "2025-10"
    assert filename == "monthly_customer_performance-2025-10.csv"
    reader = csv.DictReader(io.StringIO(text))
    assert reader.fieldnames == report.columns
    assert len(list(reader)) == report.row_count > 0
    assert "workspace revenue-ops: report rpt_test" in capsys.readouterr().out
