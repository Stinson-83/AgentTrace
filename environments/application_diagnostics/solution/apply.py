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
# handlers: keep request material (webhook URL with its token, imported rows) out of exception messages
h = APP / "taskforge" / "handlers.py"
hs = h.read_text()
hs = hs.replace('raise DeliveryError(f"POST {url} failed: name or service not known ({host})")', 'raise DeliveryError(f"delivery to {host} failed: name or service not known")')
hs = hs.replace('raise ImportValidationError(f"{len(invalid)} of {len(rows)} rows have an invalid e-mail; first bad row {invalid[0]}: {rows[invalid[0]]!r}")',
                'raise ImportValidationError(f"{len(invalid)} of {len(rows)} rows have an invalid e-mail (first bad row index {invalid[0]})")')
h.write_text(hs)
(APP / "tests" / "test_diagnostics.py").write_text((HERE / "files" / "test_diagnostics.py").read_text())
print("reference applied from", HERE.name)
