"""Traffic-facing request and response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CanMessageOut(BaseModel):
    """A CAN frame as returned by the API and streamed over the WebSocket."""

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "timestamp": 1735900000.123,
            "iso_timestamp": "2025-01-03T12:00:00.123000+00:00",
            "can_id": 768,
            "can_id_hex": "0x300",
            "is_extended_id": False,
            "dlc": 8,
            "data": "17700000010000A5",
            "channel": "vcan0",
            "direction": "RX",
            "source": "SIMULATOR",
            "message_type": "DATA",
            "flagged": False,
            "label": "Vehicle Speed",
            "decoded": {"vehicle_speed_kmh": 60.0},
        }
    })

    id: int | None = None
    timestamp: float
    iso_timestamp: str
    can_id: int
    can_id_hex: str
    is_extended_id: bool = False
    dlc: int
    data: str
    channel: str
    direction: str
    source: str
    message_type: str
    flagged: bool = False
    threat_level: str | None = None
    severity: str | None = None
    label: str | None = None
    decoded: dict[str, Any] = Field(default_factory=dict)
    attack_types: list[str] = Field(default_factory=list)


class TopCanId(BaseModel):
    can_id: int
    can_id_hex: str
    label: str | None = None
    count: int
    flagged: int = 0


class TrafficStatisticsResponse(BaseModel):
    """Aggregate view behind ``GET /api/traffic/statistics``."""

    total_messages: int
    total_bytes: int
    invalid_messages: int
    flagged_messages: int
    current_rate_msg_per_s: float
    average_rate_msg_per_s: float
    peak_rate_msg_per_s: float
    unique_can_ids: int
    window_seconds: float
    uptime_seconds: float
    last_message_at: float | None = None
    by_source: dict[str, int] = Field(default_factory=dict)
    top_can_ids: list[TopCanId] = Field(default_factory=list)
    stored_messages: int = Field(
        default=0, description="Rows currently retained in the database."
    )
    messages_by_can_id: list[TopCanId] = Field(
        default_factory=list, description="Counts from persisted history, not the live window."
    )


class RatePoint(BaseModel):
    timestamp: float
    rate_msg_per_s: float
    attacks: int = 0
    total_messages: int = 0


class TrafficRateResponse(BaseModel):
    """Instantaneous rate plus the recent history used by the dashboard chart."""

    current_rate_msg_per_s: float
    average_rate_msg_per_s: float
    peak_rate_msg_per_s: float
    window_seconds: float
    history: list[RatePoint] = Field(default_factory=list)
    flood_threshold_msg_per_s: float
    flood_suspicious_threshold_msg_per_s: float


class InjectFrameRequest(BaseModel):
    """Operator-supplied frame for ``POST /api/simulation/inject``."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "example": {"can_id": 291, "data": "DEADBEEF", "is_extended_id": False}
    })

    can_id: int = Field(ge=0, le=0x1FFFFFFF, description="Arbitration identifier.")
    data: str = Field(default="", max_length=128, description="Payload as a hex string.")
    is_extended_id: bool = False
