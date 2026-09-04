"""System status and configuration schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.runtime_config import CanRuntimeConfig, DetectionConfig, RetentionConfig


class StatusResponse(BaseModel):
    """Composite snapshot returned by ``GET /api/status``."""

    service: str
    version: str
    environment: str
    uptime_seconds: float
    started_at: float
    monitor: dict[str, Any] = Field(default_factory=dict)
    simulation: dict[str, Any] = Field(default_factory=dict)
    detection: dict[str, Any] = Field(default_factory=dict)
    traffic: dict[str, Any] = Field(default_factory=dict)
    security: dict[str, Any] = Field(default_factory=dict)
    websocket: dict[str, Any] = Field(default_factory=dict)
    storage: dict[str, Any] = Field(default_factory=dict)
    telemetry: dict[str, Any] = Field(default_factory=dict)
    config_revision: int = 1


class MonitorStatusResponse(BaseModel):
    """State of the receive loop and the CAN interface behind it."""

    running: bool
    started_at: float | None = None
    stopped_at: float | None = None
    uptime_seconds: float = 0.0
    batches_processed: int = 0
    batch_size: int = 0
    errors: int = 0
    last_error: str | None = None
    interface: dict[str, Any] | None = None
    pipeline: dict[str, Any] = Field(default_factory=dict)


class DetectionConfigPatch(BaseModel):
    """Partial update of the detection thresholds."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    event_cooldown_seconds: float | None = Field(default=None, ge=0.0, le=300.0)
    flood_threshold: float | None = Field(default=None, gt=0, le=100_000)
    flood_window_seconds: float | None = Field(default=None, gt=0, le=60)
    flood_suspicious_ratio: float | None = Field(default=None, gt=0, le=1.0)
    flood_critical_multiplier: float | None = Field(default=None, ge=1.0, le=100.0)
    per_id_flood_threshold: float | None = Field(default=None, gt=0, le=100_000)
    speed_can_id: int | None = Field(default=None, ge=0, le=0x1FFFFFFF)
    fake_speed_threshold: float | None = Field(default=None, gt=0, le=1000)
    fake_speed_suspicious_threshold: float | None = Field(default=None, gt=0, le=1000)
    fake_speed_max_acceleration: float | None = Field(default=None, gt=0, le=500)
    allowed_can_ids: list[int] | None = None
    id_anomaly_escalation_count: int | None = Field(default=None, ge=1, le=1000)
    id_anomaly_window_seconds: float | None = Field(default=None, gt=0, le=600)
    frequency_min_samples: int | None = Field(default=None, ge=3, le=1000)
    frequency_fast_ratio: float | None = Field(default=None, gt=1.0, le=100)
    frequency_slow_ratio: float | None = Field(default=None, gt=1.0, le=100)
    frequency_attack_ratio: float | None = Field(default=None, gt=1.0, le=100)


class CanConfigPatch(BaseModel):
    """Partial update of the bus parameters. Applies on the next monitor start."""

    model_config = ConfigDict(extra="forbid")

    interface: str | None = None
    channel: str | None = Field(default=None, min_length=1, max_length=64)
    bitrate: int | None = Field(default=None, ge=1000, le=8_000_000)


class RetentionConfigPatch(BaseModel):
    """Partial update of the retention limits."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    max_messages: int | None = Field(default=None, ge=1_000, le=50_000_000)
    max_security_events: int | None = Field(default=None, ge=100, le=10_000_000)
    max_system_events: int | None = Field(default=None, ge=100, le=10_000_000)
    max_age_days: int | None = Field(default=None, ge=1, le=3650)
    persist_can_messages: bool | None = None


class ConfigUpdateRequest(BaseModel):
    """Body of ``PUT /api/config``. Only the sections supplied are changed."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "example": {"detection": {"fake_speed_threshold": 180.0, "flood_threshold": 500.0}}
    })

    detection: DetectionConfigPatch | None = None
    can: CanConfigPatch | None = None
    retention: RetentionConfigPatch | None = None

    def to_patch(self) -> dict[str, Any]:
        """Drop unset fields so the merge never overwrites with ``None``."""
        patch: dict[str, Any] = {}
        for section in ("detection", "can", "retention"):
            value = getattr(self, section)
            if value is None:
                continue
            fields = value.model_dump(exclude_none=True)
            if fields:
                patch[section] = fields
        return patch


class ConfigResponse(BaseModel):
    """The current runtime configuration document."""

    revision: int
    detection: DetectionConfig
    can: CanRuntimeConfig
    retention: RetentionConfig
    changed: list[str] = Field(
        default_factory=list, description="Fields altered by this request."
    )
    restart_required: list[str] = Field(
        default_factory=list,
        description="Changed fields that only take effect after the monitor restarts.",
    )
    defaults_note: str = (
        "Detection thresholds are demonstration values, not vehicle safety limits."
    )


class SystemEventOut(BaseModel):
    """An audit-trail entry."""

    id: int | None = None
    timestamp: float
    iso_timestamp: str
    event_type: str
    message: str
    severity: str
    context: dict[str, Any] = Field(default_factory=dict)
