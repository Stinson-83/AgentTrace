"""Apply the reference implementation to /app (idempotent)."""
import sys
from pathlib import Path

APP = Path(sys.argv[1] if len(sys.argv) > 1 else "/app")
HERE = Path(__file__).resolve().parent

diag = APP / "taskforge" / "diagnostics.py"
src = diag.read_text()
src = src[: src.index("def report_failure(")] + (HERE / "files" / "diagnostics_patch.py").read_text()
if "from .observability_client import ObservabilityClient" not in src:
    src = src.replace("from .models import Job", "from .models import Job\nfrom .observability_client import ObservabilityClient")
diag.write_text(src)
(APP / "tests" / "test_diagnostics.py").write_text((HERE / "files" / "test_diagnostics.py").read_text())
print("reference applied from", HERE.name)
