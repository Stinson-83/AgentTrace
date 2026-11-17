"""Apply the reference implementation to /app (idempotent)."""
import sys
from pathlib import Path

APP = Path(sys.argv[1] if len(sys.argv) > 1 else "/app")
HERE = Path(__file__).resolve().parent

esc = APP / "deskline" / "escalation.py"
src = esc.read_text()
marker = "def escalate("
src = src[: src.index(marker)] + (HERE / "files" / "escalation_patch.py").read_text()
if "from .ticket_store import Note, Ticket, TicketStore" in src and "subject_terms" in src:
    pass
if "from .notification import NotificationRelayClient, RelayError" not in src:
    src = src.replace("from .notification import NotificationRelayClient", "from .notification import NotificationRelayClient, RelayError")
esc.write_text(src)

cli = APP / "deskline" / "cli.py"
src = cli.read_text()
if "EscalationError" not in src:
    src = src.replace("from .escalation import TicketService,", "from .escalation import EscalationError, TicketService, escalate,", 1)
if "def cmd_escalate" not in src:
    src = src.replace("\n\ndef build_parser()", (HERE / "files" / "cli_patch.py").read_text() + "\n\ndef build_parser()")
    src = src.replace('    sub.add_parser("relay-health", help="check the notification relay")',
        '    e = sub.add_parser("escalate", help="escalate a ticket and notify the tenant\'s on-call")\n'
        '    e.add_argument("--tenant", required=True); e.add_argument("--ticket", type=int, required=True)\n'
        '    e.add_argument("--reason", required=True); e.add_argument("--actor", default="cli")\n'
        '    e.set_defaults(func=cmd_escalate)\n\n'
        '    sub.add_parser("relay-health", help="check the notification relay")')
    src = src.replace('    python -m deskline.cli relay-health\n"""', '    python -m deskline.cli relay-health\n    python -m deskline.cli escalate --tenant <slug> --ticket <number> --reason "<text>" [--actor <name>]\n"""')
cli.write_text(src)
(APP / "tests" / "test_escalate.py").write_text((HERE / "files" / "test_escalate.py").read_text())
print("reference applied from", HERE.name)
