"""Environment-driven configuration.

Runtime-tunable settings (model IDs, alert schedules, receipt policy) live in the
`settings` table instead; env vars cover only what must exist before the DB unlocks.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL_CHAT = "claude-opus-4-8"
DEFAULT_MODEL_CATEGORIZE = "claude-haiku-4-5-20251001"


@dataclass(frozen=True)
class Config:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("FM_DATA_DIR", "/data")))
    backup_dir: Path = field(default_factory=lambda: Path(os.environ.get("FM_BACKUP_DIR", "/backups")))
    port: int = field(default_factory=lambda: int(os.environ.get("FM_PORT", "8000")))
    model_chat: str = field(default_factory=lambda: os.environ.get("FM_MODEL_CHAT", DEFAULT_MODEL_CHAT))
    model_categorize: str = field(
        default_factory=lambda: os.environ.get("FM_MODEL_CATEGORIZE", DEFAULT_MODEL_CATEGORIZE)
    )
    # Optional plaintext Pushover pair used ONLY for the "app is locked" boot notice,
    # since the real token is unreachable inside the locked DB.
    boot_pushover_user: str | None = field(default_factory=lambda: os.environ.get("PUSHOVER_BOOT_USER"))
    boot_pushover_token: str | None = field(default_factory=lambda: os.environ.get("PUSHOVER_BOOT_TOKEN"))
    # Base URL used in alert links (reachable over your Tailscale/LAN).
    base_url: str = field(default_factory=lambda: os.environ.get("FM_BASE_URL", "http://localhost:8000"))
    enable_scheduler: bool = field(default_factory=lambda: os.environ.get("FM_SCHEDULER", "1") != "0")
    # Seconds after the last data change before a backup snapshot fires; 0 disables.
    backup_debounce_seconds: float = field(
        default_factory=lambda: float(os.environ.get("FM_BACKUP_DEBOUNCE", "300")))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "financial_manager.db"

    @property
    def vault_meta_path(self) -> Path:
        return self.data_dir / "vault.json"
