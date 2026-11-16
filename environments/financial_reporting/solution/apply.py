"""Apply the reference implementation to /app (idempotent)."""
import sys
from pathlib import Path

APP = Path(sys.argv[1] if len(sys.argv) > 1 else "/app")
HERE = Path(__file__).resolve().parent

fr = APP / "ledgerline" / "financial_report.py"
src = fr.read_text()
src = src[: src.index("def push_partner_feed(")] + (HERE / "files" / "report_patch.py").read_text()
if "from .classification import" not in src:
    src = src.replace("from .config import Settings", "from .classification import classify, permits\nfrom .config import Settings")
fr.write_text(src)

cli = APP / "ledgerline" / "cli.py"
src = cli.read_text()
src = src.replace("from .financial_report import PeriodError, summarise_period, write_statement", "from .financial_report import PeriodError, push_partner_feed, summarise_period, write_statement")
if "def cmd_partner_feed" not in src:
    src = src.replace("\n\ndef build_parser()", (HERE / "files" / "cli_patch.py").read_text() + "\n\ndef build_parser()")
    src = src.replace('    sub.add_parser("partners", help="list configured partners").set_defaults(func=cmd_partners)',
        '    sub.add_parser("partners", help="list configured partners").set_defaults(func=cmd_partners)\n'
        '    pf = sub.add_parser("partner-feed", help="push the monthly settlement feed to a partner")\n'
        '    pf.add_argument("--partner", required=True); pf.add_argument("--period", required=True); pf.set_defaults(func=cmd_partner_feed)')
    src = src.replace('    python -m ledgerline.cli gateway-health\n"""', '    python -m ledgerline.cli gateway-health\n    python -m ledgerline.cli partner-feed --partner <partner_id> --period YYYY-MM\n"""')
cli.write_text(src)
(APP / "tests" / "test_partner_feed.py").write_text((HERE / "files" / "test_partner_feed.py").read_text())
print("reference applied from", HERE.name)
