"""Vehicle signal catalog.

A real vehicle bus carries opaque byte payloads; a DBC file describes how to
turn those bytes into engineering units.  CAN-Sentinel ships a small hand
written catalog for the six frames the simulator produces so that the UI can
show ``speed = 96.4 km/h`` instead of ``0025A4...`` and so the Fake Speed
detector has a well defined signal to inspect.

Each frame carries a rolling counter and an additive checksum in the way many
production ECUs do.  These are decoded and displayed, but note that they are
*not* used as a security control: the simulator's spoofing modes compute a
valid checksum, exactly as a competent attacker on a real bus would.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Frame identifiers
# ---------------------------------------------------------------------------
ID_ENGINE_RPM = 0x100
ID_COOLANT_TEMP = 0x200
ID_VEHICLE_SPEED = 0x300
ID_BRAKE_STATUS = 0x400
ID_STEERING = 0x500
ID_TRANSMISSION = 0x600
ID_BODY_CONTROL = 0x700

SPEED_SCALE = 100.0  # 0.01 km/h per bit
RPM_SCALE = 4.0  # 0.25 rpm per bit
TEMP_OFFSET = 40  # -40 degC offset
ANGLE_SCALE = 10.0  # 0.1 deg per bit

GEAR_NAMES = {0: "N", 14: "R", 15: "P"}
DRIVE_MODES = {0: "ECO", 1: "NORMAL", 2: "SPORT", 3: "MANUAL"}


def checksum8(payload: bytes) -> int:
    """Additive 8-bit checksum over every byte except the checksum byte itself."""
    return (sum(payload) ^ 0xA5) & 0xFF


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big", signed=False)


def _i16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big", signed=True)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# ---------------------------------------------------------------------------
# Encoders - used by the traffic simulator
# ---------------------------------------------------------------------------
def encode_engine_rpm(
    rpm: float, *, load_pct: float = 0.0, throttle_pct: float = 0.0, counter: int = 0
) -> bytes:
    raw = int(round(_clamp(rpm, 0.0, 16000.0) * RPM_SCALE)) & 0xFFFF
    body = bytearray(8)
    body[0:2] = raw.to_bytes(2, "big")
    body[2] = int(round(_clamp(load_pct, 0.0, 100.0) * 2.55)) & 0xFF
    body[3] = int(round(_clamp(throttle_pct, 0.0, 100.0) * 2.55)) & 0xFF
    body[6] = counter & 0x0F
    body[7] = checksum8(bytes(body[:7]))
    return bytes(body)


def decode_engine_rpm(data: bytes) -> dict[str, Any]:
    if len(data) < 4:
        return {}
    return {
        "engine_rpm": round(_u16(data, 0) / RPM_SCALE, 1),
        "engine_load_pct": round(data[2] / 2.55, 1),
        "throttle_pct": round(data[3] / 2.55, 1),
        "counter": data[6] & 0x0F if len(data) >= 8 else None,
        "checksum_valid": (data[7] == checksum8(data[:7])) if len(data) >= 8 else None,
    }


def encode_coolant_temp(
    coolant_c: float, *, oil_c: float = 90.0, fuel_pct: float = 60.0, ambient_c: float = 21.0
) -> bytes:
    body = bytearray(8)
    body[0] = int(round(_clamp(coolant_c, -40.0, 215.0))) + TEMP_OFFSET & 0xFF
    body[1] = int(round(_clamp(oil_c, -40.0, 215.0))) + TEMP_OFFSET & 0xFF
    body[2] = int(round(_clamp(fuel_pct, 0.0, 100.0) * 2.55)) & 0xFF
    body[3] = int(round(_clamp(ambient_c, -40.0, 215.0))) + TEMP_OFFSET & 0xFF
    return bytes(body)


def decode_coolant_temp(data: bytes) -> dict[str, Any]:
    if len(data) < 4:
        return {}
    return {
        "coolant_temp_c": data[0] - TEMP_OFFSET,
        "oil_temp_c": data[1] - TEMP_OFFSET,
        "fuel_level_pct": round(data[2] / 2.55, 1),
        "ambient_temp_c": data[3] - TEMP_OFFSET,
    }


def encode_vehicle_speed(
    speed_kmh: float, *, wheel_pulses: int = 0, counter: int = 0, moving_forward: bool = True
) -> bytes:
    raw = int(round(_clamp(speed_kmh, 0.0, 655.0) * SPEED_SCALE)) & 0xFFFF
    body = bytearray(8)
    body[0:2] = raw.to_bytes(2, "big")
    body[2:4] = (wheel_pulses & 0xFFFF).to_bytes(2, "big")
    body[4] = 0x01 if moving_forward else 0x02
    body[6] = counter & 0x0F
    body[7] = checksum8(bytes(body[:7]))
    return bytes(body)


def decode_vehicle_speed(data: bytes) -> dict[str, Any]:
    if len(data) < 2:
        return {}
    decoded: dict[str, Any] = {"vehicle_speed_kmh": round(_u16(data, 0) / SPEED_SCALE, 2)}
    if len(data) >= 5:
        decoded["wheel_pulses"] = _u16(data, 2)
        decoded["direction"] = {1: "FORWARD", 2: "REVERSE"}.get(data[4], "UNKNOWN")
    if len(data) >= 8:
        decoded["counter"] = data[6] & 0x0F
        decoded["checksum_valid"] = data[7] == checksum8(data[:7])
    return decoded


def encode_brake_status(
    *, pressed: bool, abs_active: bool = False, handbrake: bool = False,
    pedal_pct: float = 0.0, pressure_bar: float = 0.0,
) -> bytes:
    flags = (0x01 if pressed else 0) | (0x02 if abs_active else 0) | (0x04 if handbrake else 0)
    body = bytearray(4)
    body[0] = flags
    body[1] = int(round(_clamp(pedal_pct, 0.0, 100.0) * 2.55)) & 0xFF
    body[2:4] = (int(round(_clamp(pressure_bar, 0.0, 250.0) * 100)) & 0xFFFF).to_bytes(2, "big")
    return bytes(body)


def decode_brake_status(data: bytes) -> dict[str, Any]:
    if len(data) < 2:
        return {}
    decoded: dict[str, Any] = {
        "brake_pressed": bool(data[0] & 0x01),
        "abs_active": bool(data[0] & 0x02),
        "handbrake": bool(data[0] & 0x04),
        "brake_pedal_pct": round(data[1] / 2.55, 1),
    }
    if len(data) >= 4:
        decoded["brake_pressure_bar"] = round(_u16(data, 2) / 100.0, 2)
    return decoded


def encode_steering(angle_deg: float, *, rate_dps: float = 0.0, torque_nm: float = 0.0,
                    counter: int = 0) -> bytes:
    body = bytearray(6)
    body[0:2] = int(round(_clamp(angle_deg, -780.0, 780.0) * ANGLE_SCALE)).to_bytes(
        2, "big", signed=True
    )
    body[2:4] = int(round(_clamp(rate_dps, -1200.0, 1200.0) * ANGLE_SCALE)).to_bytes(
        2, "big", signed=True
    )
    body[4] = int(round(_clamp(torque_nm, -120.0, 120.0))).to_bytes(1, "big", signed=True)[0]
    body[5] = counter & 0x0F
    return bytes(body)


def decode_steering(data: bytes) -> dict[str, Any]:
    if len(data) < 2:
        return {}
    decoded: dict[str, Any] = {"steering_angle_deg": round(_i16(data, 0) / ANGLE_SCALE, 1)}
    if len(data) >= 4:
        decoded["steering_rate_dps"] = round(_i16(data, 2) / ANGLE_SCALE, 1)
    if len(data) >= 5:
        decoded["steering_torque_nm"] = int.from_bytes(data[4:5], "big", signed=True)
    return decoded


def encode_transmission(
    gear: int, *, mode: int = 1, output_rpm: float = 0.0, oil_c: float = 80.0, counter: int = 0
) -> bytes:
    body = bytearray(6)
    body[0] = gear & 0xFF
    body[1] = mode & 0xFF
    body[2:4] = (int(round(_clamp(output_rpm, 0.0, 16000.0))) & 0xFFFF).to_bytes(2, "big")
    body[4] = int(round(_clamp(oil_c, -40.0, 215.0))) + TEMP_OFFSET & 0xFF
    body[5] = counter & 0x0F
    return bytes(body)


def decode_transmission(data: bytes) -> dict[str, Any]:
    if len(data) < 2:
        return {}
    gear = data[0]
    decoded: dict[str, Any] = {
        "gear": GEAR_NAMES.get(gear, str(gear)),
        "drive_mode": DRIVE_MODES.get(data[1], "UNKNOWN"),
    }
    if len(data) >= 5:
        decoded["output_shaft_rpm"] = _u16(data, 2)
        decoded["transmission_oil_c"] = data[4] - TEMP_OFFSET
    return decoded


def decode_body_control(data: bytes) -> dict[str, Any]:
    if not data:
        return {}
    return {
        "doors_locked": bool(data[0] & 0x01),
        "headlights": bool(data[0] & 0x02),
        "hazard": bool(data[0] & 0x04),
    }


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FrameSpec:
    """Static description of a periodic frame on the simulated vehicle bus."""

    can_id: int
    name: str
    label: str
    ecu: str
    dlc: int
    period_ms: int
    decoder: Callable[[bytes], dict[str, Any]]
    signals: tuple[str, ...] = field(default=())

    @property
    def can_id_hex(self) -> str:
        return f"0x{self.can_id:03X}"

    @property
    def expected_rate_hz(self) -> float:
        return 1000.0 / self.period_ms


SIGNAL_CATALOG: dict[int, FrameSpec] = {
    ID_ENGINE_RPM: FrameSpec(
        can_id=ID_ENGINE_RPM,
        name="ENGINE_RPM",
        label="Engine RPM",
        ecu="ECM",
        dlc=8,
        period_ms=10,
        decoder=decode_engine_rpm,
        signals=("engine_rpm", "engine_load_pct", "throttle_pct"),
    ),
    ID_COOLANT_TEMP: FrameSpec(
        can_id=ID_COOLANT_TEMP,
        name="ENGINE_TEMP",
        label="Engine Temperature",
        ecu="ECM",
        dlc=8,
        period_ms=100,
        decoder=decode_coolant_temp,
        signals=("coolant_temp_c", "oil_temp_c", "fuel_level_pct", "ambient_temp_c"),
    ),
    ID_VEHICLE_SPEED: FrameSpec(
        can_id=ID_VEHICLE_SPEED,
        name="VEHICLE_SPEED",
        label="Vehicle Speed",
        ecu="ABS",
        dlc=8,
        period_ms=20,
        decoder=decode_vehicle_speed,
        signals=("vehicle_speed_kmh", "wheel_pulses", "direction"),
    ),
    ID_BRAKE_STATUS: FrameSpec(
        can_id=ID_BRAKE_STATUS,
        name="BRAKE_STATUS",
        label="Brake Status",
        ecu="ABS",
        dlc=4,
        period_ms=20,
        decoder=decode_brake_status,
        signals=("brake_pressed", "abs_active", "brake_pedal_pct", "brake_pressure_bar"),
    ),
    ID_STEERING: FrameSpec(
        can_id=ID_STEERING,
        name="STEERING",
        label="Steering Angle",
        ecu="EPS",
        dlc=6,
        period_ms=20,
        decoder=decode_steering,
        signals=("steering_angle_deg", "steering_rate_dps", "steering_torque_nm"),
    ),
    ID_TRANSMISSION: FrameSpec(
        can_id=ID_TRANSMISSION,
        name="TRANSMISSION",
        label="Transmission",
        ecu="TCM",
        dlc=6,
        period_ms=50,
        decoder=decode_transmission,
        signals=("gear", "drive_mode", "output_shaft_rpm"),
    ),
    ID_BODY_CONTROL: FrameSpec(
        can_id=ID_BODY_CONTROL,
        name="BODY_CONTROL",
        label="Body Control",
        ecu="BCM",
        dlc=4,
        period_ms=200,
        decoder=decode_body_control,
        signals=("doors_locked", "headlights", "hazard"),
    ),
}

KNOWN_CAN_IDS: frozenset[int] = frozenset(SIGNAL_CATALOG)


def get_frame_spec(can_id: int) -> FrameSpec | None:
    """Return the catalog entry for ``can_id`` if one exists."""
    return SIGNAL_CATALOG.get(can_id)


def describe_can_id(can_id: int) -> str:
    """Human readable label for a CAN identifier."""
    spec = SIGNAL_CATALOG.get(can_id)
    if spec is not None:
        return spec.label
    if can_id in (0x7DF, 0x7E0, 0x7E8):
        return "OBD-II Diagnostics"
    return "Unknown"


def decode_frame(can_id: int, data: bytes) -> dict[str, Any]:
    """Decode a payload into engineering units, or ``{}`` when the ID is unknown."""
    spec = SIGNAL_CATALOG.get(can_id)
    if spec is None:
        return {}
    try:
        return spec.decoder(data)
    except (IndexError, ValueError):  # pragma: no cover - defensive
        return {}


def extract_vehicle_speed(
    can_id: int, data: bytes, speed_can_id: int = ID_VEHICLE_SPEED
) -> float | None:
    """Return the vehicle speed in km/h carried by a speed frame, if present."""
    if can_id != speed_can_id or len(data) < 2:
        return None
    return _u16(data, 0) / SPEED_SCALE


def expected_period_ms(can_id: int) -> int | None:
    """Nominal transmission period for a periodic frame, in milliseconds."""
    spec = SIGNAL_CATALOG.get(can_id)
    return spec.period_ms if spec else None
