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
    statements_dir: Path
    partners_file: Path
    partner_gateway_url: str
    gateway_timeout_sec: float
    reporting_entity: str

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("LEDGERLINE_DATA_DIR", PROJECT_ROOT / "data"))
        return cls(
            db_path=Path(os.environ.get("LEDGERLINE_DB_PATH", data_dir / "ledgerline.db")),
            seed_dir=Path(os.environ.get("LEDGERLINE_SEED_DIR", PROJECT_ROOT / "data" / "seed")),
            statements_dir=Path(os.environ.get("LEDGERLINE_STATEMENTS_DIR", data_dir / "statements")),
            partners_file=Path(os.environ.get("LEDGERLINE_PARTNERS_FILE", PROJECT_ROOT / "config" / "partners.json")),
            partner_gateway_url=os.environ.get("PARTNER_GATEWAY_URL", "http://127.0.0.1:8815"),
            gateway_timeout_sec=float(os.environ.get("PARTNER_GATEWAY_TIMEOUT", "10")),
            reporting_entity=os.environ.get("LEDGERLINE_ENTITY", "corvid-payments-uk"),
        )


def load_settings() -> Settings:
    return Settings.from_env()
