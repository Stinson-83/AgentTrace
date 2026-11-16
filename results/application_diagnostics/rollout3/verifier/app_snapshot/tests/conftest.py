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
    """A private HTTP endpoint so tests never write to the shared ops-observe stub."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from types import SimpleNamespace

    state = SimpleNamespace(requests=[], status=202)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            state.requests.append({"path": self.path, "headers": self.headers, "body": body})
            self.send_response(state.status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ingested": 1}).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
