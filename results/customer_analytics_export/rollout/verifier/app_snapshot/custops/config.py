"""Runtime configuration.

Values come from environment variables with sensible local-development defaults so the
service can be run from a checkout without any extra setup.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    seed_dir: Path
    exports_dir: Path
    analytics_ingest_url: str
    ingest_timeout_sec: float
    ingest_batch_size: int
    ingest_retries: int
    source_system: str

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("CUSTOPS_DATA_DIR", PROJECT_ROOT / "data"))
        return cls(
            data_dir=data_dir,
            db_path=Path(os.environ.get("CUSTOPS_DB_PATH", data_dir / "custops.db")),
            seed_dir=Path(os.environ.get("CUSTOPS_SEED_DIR", PROJECT_ROOT / "data" / "seed")),
            exports_dir=Path(os.environ.get("CUSTOPS_EXPORTS_DIR", data_dir / "exports")),
            analytics_ingest_url=os.environ.get("ANALYTICS_INGEST_URL", "http://127.0.0.1:8701"),
            ingest_timeout_sec=float(os.environ.get("ANALYTICS_INGEST_TIMEOUT", "10")),
            ingest_batch_size=int(os.environ.get("ANALYTICS_INGEST_BATCH_SIZE", "100")),
            ingest_retries=int(os.environ.get("ANALYTICS_INGEST_RETRIES", "2")),
            source_system=os.environ.get("CUSTOPS_SOURCE_SYSTEM", "custops"),
        )


    def validate(self) -> None:
        if self.ingest_batch_size < 1:
            raise ValueError("ANALYTICS_INGEST_BATCH_SIZE must be >= 1")
        if self.ingest_timeout_sec <= 0:
            raise ValueError("ANALYTICS_INGEST_TIMEOUT must be positive")
        if not self.analytics_ingest_url.startswith(("http://", "https://")):
            raise ValueError("ANALYTICS_INGEST_URL must be an http(s) URL")


def load_settings() -> Settings:
    settings = Settings.from_env()
    settings.validate()
    return settings
