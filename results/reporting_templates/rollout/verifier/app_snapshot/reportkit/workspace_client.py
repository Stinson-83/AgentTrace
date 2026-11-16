"""Client for the reporting workspace service (publishes CSV reports into a workspace)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

from .report_engine import Report


class WorkspaceError(RuntimeError):
    pass


@dataclass
class PublishResponse:
    status: int
    body: dict[str, Any]


class WorkspaceClient:
    def __init__(self, base_url: str, timeout_sec: float = 10.0, publisher: str = "reportkit"):
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.publisher = publisher

    @staticmethod
    def _multipart(fields: dict[str, str], filename: str, content: bytes) -> tuple[bytes, str]:
        boundary = "reportkit-" + uuid.uuid4().hex
        parts = []
        for k, v in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8"))
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: text/csv\r\n\r\n'.encode("utf-8") + content + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        return b"".join(parts), f"multipart/form-data; boundary={boundary}"

    def publish(self, workspace: str, report: Report, csv_text: str, filename: str) -> PublishResponse:
        body, content_type = self._multipart(
            {"name": f"{report.template} {report.period}", "template": report.template, "period": report.period,
             "publisher": self.publisher, "rows": str(report.row_count)}, filename, csv_text.encode("utf-8"))
        req = urllib.request.Request(f"{self.base_url}/workspaces/{workspace}/reports", data=body, method="POST",
                                     headers={"Content-Type": content_type, "X-Publisher": self.publisher})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
                return PublishResponse(resp.status, json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raise WorkspaceError(f"workspace rejected the report ({e.code}): {e.read().decode('utf-8', 'replace')}") from e
        except urllib.error.URLError as e:
            raise WorkspaceError(f"workspace unreachable at {self.base_url}: {e.reason}") from e

    def health(self) -> PublishResponse:
        try:
            with urllib.request.urlopen(self.base_url + "/healthz", timeout=self.timeout_sec) as resp:
                return PublishResponse(resp.status, json.loads(resp.read().decode("utf-8")))
        except urllib.error.URLError as e:
            raise WorkspaceError(f"workspace unreachable at {self.base_url}: {e.reason}") from e
