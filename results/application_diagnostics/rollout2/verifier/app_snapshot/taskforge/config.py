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
    output_dir: Path
    failure_log: Path
    observe_url: str
    observe_timeout_sec: float
    max_attempts: int
    service_name: str
    environment: str

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("TASKFORGE_DATA_DIR", PROJECT_ROOT / "data"))
        return cls(
            db_path=Path(os.environ.get("TASKFORGE_DB_PATH", data_dir / "taskforge.db")),
            seed_dir=Path(os.environ.get("TASKFORGE_SEED_DIR", PROJECT_ROOT / "data" / "seed")),
            output_dir=Path(os.environ.get("TASKFORGE_OUTPUT_DIR", data_dir / "output")),
            failure_log=Path(os.environ.get("TASKFORGE_FAILURE_LOG", data_dir / "failures.jsonl")),
            observe_url=os.environ.get("OPS_OBSERVE_URL", "http://127.0.0.1:8790"),
            observe_timeout_sec=float(os.environ.get("OPS_OBSERVE_TIMEOUT", "10")),
            max_attempts=int(os.environ.get("TASKFORGE_MAX_ATTEMPTS", "3")),
            service_name=os.environ.get("TASKFORGE_SERVICE_NAME", "taskforge"),
            environment=os.environ.get("TASKFORGE_ENV", "staging"),
        )


def load_settings() -> Settings:
    return Settings.from_env()
