"""Simulation control schemas."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.simulation.modes import CustomFrame, SimulationMode, SimulationProfile


class SimulationRequest(BaseModel):
    """Body for ``POST /api/simulation/start`` and ``/api/simulation/mode``.

    Every field is optional; omitted values keep whatever the service is
    already configured with, so switching mode does not silently reset the
    attack parameters an operator tuned a moment ago.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "example": {"mode": "FAKE_SPEED", "fake_speed_value": 255.0, "fake_speed_rate": 100.0}
    })

    mode: SimulationMode | None = None
    flood_rate: float | None = Field(default=None, gt=0, le=20_000)
    flood_can_id: int | None = Field(default=None, ge=0, le=0x1FFFFFFF)
    fake_speed_value: float | None = Field(default=None, ge=0, le=655)
    fake_speed_rate: float | None = Field(default=None, gt=0, le=5000)
    traffic_scale: float | None = Field(default=None, gt=0, le=10.0)
    custom_frames: list[CustomFrame] | None = None

    @model_validator(mode="after")
    def _require_frames_for_custom(self) -> Self:
        if self.mode is SimulationMode.CUSTOM and not self.custom_frames:
            raise ValueError("CUSTOM mode requires at least one entry in custom_frames")
        return self

    def apply_to(self, current: SimulationProfile) -> SimulationProfile:
        """Merge this request onto the active profile."""
        patch = self.model_dump(exclude_none=True)
        merged = current.model_dump()
        merged.update(patch)
        return SimulationProfile.model_validate(merged)


class SimulationModeOption(BaseModel):
    value: str
    label: str
    is_attack: bool


class SimulationStatusResponse(BaseModel):
    """State of the traffic generator."""

    running: bool
    mode: str
    mode_label: str
    attack_active: bool
    profile: dict[str, Any] = Field(default_factory=dict)
    started_at: float | None = None
    stopped_at: float | None = None
    last_started: float | None = None
    uptime_seconds: float = 0.0
    generated_rate_msg_per_s: float = 0.0
    messages_generated: int = 0
    normal_messages: int = 0
    attack_messages: int = 0
    errors: int = 0
    last_error: str | None = None
    vehicle: dict[str, Any] | None = None
    available_modes: list[SimulationModeOption] = Field(default_factory=list)
    monitor_started: bool | None = Field(
        default=None,
        description="True when starting the simulation also had to start the monitor.",
    )
    previous_mode: str | None = None
