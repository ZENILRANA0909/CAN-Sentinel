"""Security-event request and response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.security_event import EventStatus


class SecurityEventOut(BaseModel):
    """A persisted security event."""

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "id": 42,
            "timestamp": 1735900000.5,
            "iso_timestamp": "2025-01-03T12:00:00.500000+00:00",
            "attack_type": "FAKE_SPEED",
            "threat_level": "ATTACK",
            "severity": "HIGH",
            "detector": "fake_speed",
            "can_id": 768,
            "can_id_hex": "0x300",
            "confidence": 0.93,
            "description": "Forged vehicle speed: 255.0 km/h reported on 0x300",
            "evidence": {"observed_speed_kmh": 255.0, "attack_threshold_kmh": 200.0},
            "status": "NEW",
        }
    })

    id: int | None = None
    timestamp: float
    iso_timestamp: str
    attack_type: str
    threat_level: str
    severity: str
    detector: str
    can_id: int | None = None
    can_id_hex: str | None = None
    confidence: float
    description: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: str = EventStatus.NEW.value
    channel: str | None = None
    label: str | None = None


class EventStatusUpdate(BaseModel):
    """Body of ``PATCH /api/attacks/{event_id}``."""

    model_config = ConfigDict(extra="forbid")

    status: EventStatus


class AttackStatisticsResponse(BaseModel):
    """Aggregate security posture behind ``GET /api/attacks/statistics``."""

    total_events: int
    events_last_hour: int
    live_attacks_total: int = Field(description="Events counted since the process started.")
    active_alerts: int
    threat_level: str
    by_attack_type: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    by_detector: dict[str, int] = Field(default_factory=dict)
    top_can_ids: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    bucket_seconds: int = 60


class DetectorSummary(BaseModel):
    name: str
    attack_type: str
    description: str
    enabled: bool
    inspections: int
    detections: int
    state: dict[str, Any] = Field(default_factory=dict)


class SecuritySummaryResponse(BaseModel):
    """One-call summary used to render the Dashboard header."""

    threat_level: str
    active_alerts: int
    attacks_total: int
    events_stored: int
    events_last_hour: int
    by_attack_type: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
    recent_events: list[SecurityEventOut] = Field(default_factory=list)
    detectors: list[DetectorSummary] = Field(default_factory=list)
    monitor_running: bool = False
    simulation_running: bool = False
