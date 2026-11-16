"""Runtime settings with local-development defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    db_path: Path
    seed_dir: Path
    reports_dir: Path
    workspace_url: str
    workspace_timeout_sec: float
    publisher: str

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("REPORTKIT_DATA_DIR", PROJECT_ROOT / "data"))
        return cls(
            db_path=Path(os.environ.get("REPORTKIT_DB_PATH", data_dir / "reportkit.db")),
            seed_dir=Path(os.environ.get("REPORTKIT_SEED_DIR", PROJECT_ROOT / "data" / "seed")),
            reports_dir=Path(os.environ.get("REPORTKIT_REPORTS_DIR", data_dir / "reports")),
            workspace_url=os.environ.get("WORKSPACE_URL", "http://127.0.0.1:8760"),
            workspace_timeout_sec=float(os.environ.get("WORKSPACE_TIMEOUT", "10")),
            publisher=os.environ.get("REPORTKIT_PUBLISHER", "reportkit"),
        )


def load_settings() -> Settings:
    return Settings.from_env()
