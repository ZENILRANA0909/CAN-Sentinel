"""Application settings.

Every tunable value in CAN-Sentinel is resolved here, from environment
variables (optionally via a ``.env`` file).  Nothing in the codebase is allowed
to read ``os.environ`` directly - that keeps configuration auditable and makes
the whole system trivially reconfigurable from the environment, CI or a test fixture.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.version import SERVICE_NAME, __version__

# Repository root: <root>/backend/app/core/config.py -> parents[3]
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent

AppEnv = Literal["development", "testing", "production"]
CanBackend = Literal["virtual", "python-can", "mock"]


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_can_id(raw: str | int) -> int:
    """Parse a CAN identifier written as ``0x300``, ``300`` or an int."""
    if isinstance(raw, int):
        return raw
    text = str(raw).strip().lower()
    if not text:
        raise ValueError("empty CAN identifier")
    return int(text, 16) if text.startswith("0x") else int(text, 10)


class Settings(BaseSettings):
    """Immutable process-level configuration loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Application -------------------------------------------------------
    app_env: AppEnv = "development"
    app_name: str = SERVICE_NAME
    app_version: str = __version__
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api"

    # ---- CORS --------------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://localhost:3000"

    # ---- Logging -----------------------------------------------------------
    log_level: str = "INFO"
    log_dir: Path = PROJECT_ROOT / "logs"
    log_file: str = "can-sentinel.log"
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 5
    log_json: bool = False
    log_to_file: bool = True

    # ---- CAN interface -----------------------------------------------------
    can_interface: CanBackend = "virtual"
    can_channel: str = "can0"
    can_bitrate: int = 500_000
    can_bustype: str = "socketcan"
    can_receive_queue_size: int = 20_000

    # ---- Detection: flood --------------------------------------------------
    flood_threshold: float = Field(default=600.0, gt=0)
    flood_window_seconds: float = Field(default=1.0, gt=0)
    flood_suspicious_ratio: float = Field(default=0.7, gt=0, le=1.0)
    flood_critical_multiplier: float = Field(default=2.0, ge=1.0)
    per_id_flood_threshold: float = Field(default=200.0, gt=0)

    # ---- Detection: fake speed --------------------------------------------
    speed_can_id: str = "0x300"
    fake_speed_threshold: float = Field(default=200.0, gt=0)
    fake_speed_suspicious_threshold: float = Field(default=120.0, gt=0)
    fake_speed_max_acceleration: float = Field(default=15.0, gt=0)

    # ---- Detection: identifier allowlist ----------------------------------
    allowed_can_ids: str = "0x100,0x200,0x300,0x400,0x500,0x600,0x700,0x7DF,0x7E0,0x7E8"
    id_anomaly_escalation_count: int = Field(default=5, ge=1)
    id_anomaly_window_seconds: float = Field(default=5.0, gt=0)

    # ---- Detection: frequency ---------------------------------------------
    frequency_min_samples: int = Field(default=12, ge=3)
    frequency_fast_ratio: float = Field(default=2.5, gt=1.0)
    frequency_slow_ratio: float = Field(default=2.5, gt=1.0)
    frequency_attack_ratio: float = Field(default=5.0, gt=1.0)

    # ---- Detection engine --------------------------------------------------
    detection_enabled: bool = True
    detection_event_cooldown_seconds: float = Field(default=2.0, ge=0)

    # ---- Database ----------------------------------------------------------
    database_url: str = "sqlite:///./data/can_sentinel.db"
    db_echo: bool = False
    db_write_queue_size: int = 20_000
    db_write_batch_size: int = 500
    db_write_interval_seconds: float = Field(default=0.5, gt=0)
    persist_can_messages: bool = True

    # ---- Retention ---------------------------------------------------------
    retention_enabled: bool = True
    retention_interval_seconds: float = Field(default=60.0, gt=0)
    retention_max_messages: int = Field(default=200_000, ge=1000)
    retention_max_security_events: int = Field(default=50_000, ge=100)
    retention_max_system_events: int = Field(default=20_000, ge=100)
    retention_days: int = Field(default=7, ge=1)

    # ---- Simulator ---------------------------------------------------------
    simulator_autostart: bool = False
    monitor_autostart: bool = True
    simulator_flood_rate: float = Field(default=1200.0, gt=0)
    simulator_fake_speed_value: float = Field(default=255.0, gt=0)
    simulator_max_rate: float = Field(default=5000.0, gt=0)

    # ---- WebSocket / streaming --------------------------------------------
    ws_flush_interval_ms: int = Field(default=250, ge=50, le=5000)
    ws_max_messages_per_flush: int = Field(default=40, ge=1, le=500)
    ws_max_clients: int = Field(default=32, ge=1)
    ws_client_queue_size: int = Field(default=200, ge=10)

    # ---- In-memory history -------------------------------------------------
    history_buffer_size: int = Field(default=2000, ge=100)
    statistics_window_seconds: float = Field(default=10.0, gt=0)

    # ------------------------------------------------------------------ #
    # Validators / derived values                                        #
    # ------------------------------------------------------------------ #
    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        if level not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return level

    @property
    def cors_origin_list(self) -> list[str]:
        return _split_csv(self.cors_origins)

    @property
    def allowed_can_id_set(self) -> set[int]:
        return {parse_can_id(item) for item in _split_csv(self.allowed_can_ids)}

    @property
    def speed_can_id_int(self) -> int:
        return parse_can_id(self.speed_can_id)

    @property
    def log_path(self) -> Path:
        return self.log_dir / self.log_file

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def resolved_database_url(self) -> str:
        """Database URL with any relative SQLite path anchored to the project root.

        Without this, ``sqlite:///./data/can_sentinel.db`` would resolve against
        whatever directory the process happened to start in - which is why the
        app and Alembic must both go through this property.
        """
        path = self.sqlite_path
        if path is None:
            return self.database_url
        return f"sqlite:///{path.as_posix()}"

    @property
    def sqlite_path(self) -> Path | None:
        """Filesystem path backing a SQLite URL, or ``None`` for other engines."""
        url = self.database_url
        if not url.startswith("sqlite"):
            return None
        _, _, tail = url.partition(":///")
        if not tail or tail == ":memory:":
            return None
        path = Path(tail)
        return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached process-wide settings instance."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear the settings cache (used by tests that patch the environment)."""
    get_settings.cache_clear()
