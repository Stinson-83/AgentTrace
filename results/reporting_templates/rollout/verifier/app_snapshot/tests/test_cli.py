import csv
import io

from reportkit import cli
from reportkit.templates import get_template
from reportkit.workspace_client import PublishResponse


def test_monthly_customer_performance_run_and_publish(store, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_store", lambda settings: store)
    monkeypatch.setenv("REPORTKIT_REPORTS_DIR", str(tmp_path))
    template = "monthly_customer_performance"
    args = ["--template", template, "--period", "2025-10"]
    assert cli.main(["report", "run", *args]) == 0
    filename = f"{template}-2025-10.csv"
    csv_text = (tmp_path / filename).read_text()
    reader = csv.DictReader(io.StringIO(csv_text))
    assert reader.fieldnames == get_template(template).columns
    rows = list(reader)
    assert rows and all(row["period"] == "2025-10" for row in rows)
    calls = []

    def publish(self, workspace, report, content, uploaded_filename):
        calls.append(workspace)
        assert report.template == template and report.period == "2025-10"
        assert report.row_count == len(rows)
        assert content == csv_text
        assert uploaded_filename == filename
        return PublishResponse(201, {"report_id": "test-report"})

    monkeypatch.setattr(cli.WorkspaceClient, "publish", publish)
    assert cli.main(["report", "publish", *args]) == 0
    assert calls == ["revenue-ops"]
    assert "workspace revenue-ops: report test-report" in capsys.readouterr().out
