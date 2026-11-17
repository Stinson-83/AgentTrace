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
    relay_url: str
    relay_timeout_sec: float
    cache_size: int
    sla_hours: dict[str, int]
    oncall_channel: str

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("DESKLINE_DATA_DIR", PROJECT_ROOT / "data"))
        return cls(
            db_path=Path(os.environ.get("DESKLINE_DB_PATH", data_dir / "deskline.db")),
            seed_dir=Path(os.environ.get("DESKLINE_SEED_DIR", PROJECT_ROOT / "data" / "seed")),
            relay_url=os.environ.get("NOTIFY_RELAY_URL", "http://127.0.0.1:8742"),
            relay_timeout_sec=float(os.environ.get("NOTIFY_RELAY_TIMEOUT", "10")),
            cache_size=int(os.environ.get("DESKLINE_CACHE_SIZE", "256")),
            sla_hours={"urgent": 4, "high": 8, "normal": 24, "low": 72},
            oncall_channel=os.environ.get("DESKLINE_ONCALL_CHANNEL", "/channels/oncall"),
        )


def load_settings() -> Settings:
    return Settings.from_env()
