import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from taskforge.config import Settings  # noqa: E402
from taskforge.job_store import JobStore  # noqa: E402


@pytest.fixture()
def settings(tmp_path):
    return Settings(db_path=tmp_path / "jobs.db", seed_dir=ROOT / "data" / "seed", output_dir=tmp_path / "out",
                    failure_log=tmp_path / "failures.jsonl", observe_url="http://127.0.0.1:1", observe_timeout_sec=1,
                    max_attempts=3, service_name="taskforge-test", environment="test")


@pytest.fixture()
def store(settings):
    s = JobStore(settings.db_path)
    s.load_seed(settings.seed_dir)
    yield s
    s.close()


@pytest.fixture()
def observe_server():
    """An isolated ops-observe stand-in that captures the actual HTTP requests."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from types import SimpleNamespace

    state = SimpleNamespace(status=202, requests=[])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            state.requests.append({"path": self.path, "headers": self.headers, "body": body})
            data = json.dumps({"ingested": 1} if state.status == 202 else {"error": "rejected"}).encode()
            self.send_response(state.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
