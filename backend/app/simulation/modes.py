"""Simulation modes and the tunable profile behind each one."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.can.message import CLASSIC_MAX_PAYLOAD, coerce_payload


class SimulationMode(str, Enum):
    """What the simulator is currently generating."""

    NORMAL = "NORMAL"
    FAKE_SPEED = "FAKE_SPEED"
    CAN_FLOOD = "CAN_FLOOD"
    MIXED = "MIXED"
    CUSTOM = "CUSTOM"

    @property
    def is_attack(self) -> bool:
        return self in {SimulationMode.FAKE_SPEED, SimulationMode.CAN_FLOOD, SimulationMode.MIXED}

    @property
    def label(self) -> str:
        return {
            SimulationMode.NORMAL: "Normal vehicle traffic",
            SimulationMode.FAKE_SPEED: "Fake speed injection",
            SimulationMode.CAN_FLOOD: "Bus flood (denial of service)",
            SimulationMode.MIXED: "Fake speed + bus flood",
            SimulationMode.CUSTOM: "Custom frame injection",
        }[self]


class CustomFrame(BaseModel):
    """One user-defined frame injected repeatedly in CUSTOM mode."""

    model_config = ConfigDict(extra="forbid")

    can_id: int = Field(ge=0, le=0x1FFFFFFF)
    data: str = Field(default="", description="Payload as a hex string, e.g. 'DEADBEEF'.")
    interval_ms: int = Field(default=100, ge=1, le=60_000)
    is_extended_id: bool = False

    @field_validator("data")
    @classmethod
    def _validate_payload(cls, value: str) -> str:
        payload = coerce_payload(value)
        if len(payload) > CLASSIC_MAX_PAYLOAD:
            raise ValueError(f"payload exceeds the {CLASSIC_MAX_PAYLOAD}-byte classic CAN limit")
        return payload.hex().upper()

    @property
    def payload(self) -> bytes:
        return bytes.fromhex(self.data) if self.data else b""


class SimulationProfile(BaseModel):
    """Per-run simulator parameters, supplied when starting or switching mode."""

    model_config = ConfigDict(extra="forbid")

    mode: SimulationMode = SimulationMode.NORMAL

    #: Frames per second injected in CAN_FLOOD / MIXED mode.
    flood_rate: float = Field(default=1200.0, gt=0, le=20_000)
    #: Identifier used by the flood. 0x000 is the highest-priority identifier on
    #: a CAN bus, which is what a real denial-of-service injector would choose.
    flood_can_id: int = Field(default=0x000, ge=0, le=0x1FFFFFFF)

    #: Speed value, in km/h, written into spoofed speed frames.
    fake_speed_value: float = Field(default=255.0, ge=0, le=655)
    #: Rate of injected speed frames. The genuine ECU keeps transmitting at its
    #: own 50 Hz, so the identifier's total rate rises - which is exactly what a
    #: frequency detector is meant to notice.
    fake_speed_rate: float = Field(default=100.0, gt=0, le=5000)

    custom_frames: list[CustomFrame] = Field(default_factory=list)

    #: Multiplier applied to the normal vehicle traffic rate (1.0 = realistic).
    traffic_scale: float = Field(default=1.0, gt=0, le=10.0)

    def describe(self) -> dict[str, object]:
        payload: dict[str, object] = {"mode": self.mode.value, "label": self.mode.label}
        if self.mode in {SimulationMode.CAN_FLOOD, SimulationMode.MIXED}:
            payload["flood_rate"] = self.flood_rate
            payload["flood_can_id"] = f"0x{self.flood_can_id:03X}"
        if self.mode in {SimulationMode.FAKE_SPEED, SimulationMode.MIXED}:
            payload["fake_speed_value"] = self.fake_speed_value
            payload["fake_speed_rate"] = self.fake_speed_rate
        if self.mode is SimulationMode.CUSTOM:
            payload["custom_frames"] = len(self.custom_frames)
        return payload
