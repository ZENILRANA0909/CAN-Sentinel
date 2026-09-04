"""Fake Speed (speed spoofing) detector.

A classic CAN attack injects forged vehicle-speed frames so that downstream
ECUs, the instrument cluster or an ADAS function act on a speed the car is not
actually travelling at.  Two independent signals are checked:

1. **Magnitude** - a reported speed beyond the configured plausible range.
2. **Kinematics** - a speed change no real vehicle could physically produce,
   which catches a spoofed value that is still inside the normal range.

The thresholds are demonstration values (see ``docs/detection.md``); they are
not derived from a vehicle safety standard.
"""

from __future__ import annotations

from typing import Any

from app.can.message import CanMessage
from app.can.signals import extract_vehicle_speed
from app.detection.base import (
    AttackDetector,
    AttackType,
    DetectionResult,
    Severity,
    ThreatLevel,
)

#: A speed frame carries at least a 16-bit speed value.
MIN_SPEED_PAYLOAD = 2
#: Ignore kinematic checks across gaps longer than this - a long gap means we
#: simply were not observing, not that the vehicle teleported.
MAX_KINEMATIC_GAP_SECONDS = 2.0
#: Below this many seconds the timestamp resolution is not trustworthy enough
#: to compute an acceleration.
MIN_KINEMATIC_GAP_SECONDS = 1e-4


class FakeSpeedDetector(AttackDetector):
    """Detect implausible or forged vehicle-speed frames."""

    name = "fake_speed"
    attack_type = AttackType.FAKE_SPEED
    description = (
        "Flags vehicle-speed frames reporting an implausible magnitude or a "
        "physically impossible rate of change."
    )

    def __init__(self, config_service: Any) -> None:
        super().__init__(config_service)
        self._last_speed: float | None = None
        self._last_timestamp: float | None = None
        self._peak_speed: float = 0.0

    def reset(self) -> None:
        self._last_speed = None
        self._last_timestamp = None
        self._peak_speed = 0.0

    # ------------------------------------------------------------------ #
    def _inspect(self, message: CanMessage) -> DetectionResult:
        config = self.config
        if message.arbitration_id != config.speed_can_id:
            return self._normal(message, description="Not a vehicle-speed frame")

        if len(message.data) < MIN_SPEED_PAYLOAD:
            # A speed frame too short to carry a speed value is itself a
            # spoofing indicator: a genuine ECU always emits the full frame.
            return DetectionResult(
                detector=self.name,
                detected=True,
                threat_level=ThreatLevel.SUSPICIOUS,
                attack_type=AttackType.FAKE_SPEED,
                severity=Severity.MEDIUM,
                confidence=0.5,
                can_id=message.arbitration_id,
                timestamp=message.timestamp,
                description=(
                    f"Malformed speed frame: {len(message.data)} byte(s), "
                    f"at least {MIN_SPEED_PAYLOAD} required to decode a speed"
                ),
                evidence={
                    "can_id": message.can_id_hex,
                    "dlc": message.dlc,
                    "payload": message.data_hex,
                    "reason": "payload_too_short",
                },
            )

        speed = extract_vehicle_speed(
            message.arbitration_id, message.data, speed_can_id=config.speed_can_id
        )
        if speed is None:  # pragma: no cover - guarded by the length check above
            return self._normal(message, description="Speed value not decodable")

        acceleration = self._acceleration(speed, message.timestamp)
        self._peak_speed = max(self._peak_speed, speed)
        previous_speed = self._last_speed

        base_evidence: dict[str, Any] = {
            "attack_type": AttackType.FAKE_SPEED.value,
            "can_id": message.can_id_hex,
            "observed_speed_kmh": round(speed, 2),
            "suspicious_threshold_kmh": config.fake_speed_suspicious_threshold,
            "attack_threshold_kmh": config.fake_speed_threshold,
            "payload": message.data_hex,
        }
        if previous_speed is not None:
            base_evidence["previous_speed_kmh"] = round(previous_speed, 2)
        if acceleration is not None:
            base_evidence["acceleration_kmh_per_s"] = round(acceleration, 2)

        # --- 1. Magnitude ------------------------------------------------
        if speed > config.fake_speed_threshold:
            excess = speed - config.fake_speed_threshold
            extreme = speed >= config.fake_speed_threshold * 1.5
            confidence = min(1.0, 0.75 + (excess / max(config.fake_speed_threshold, 1.0)) * 0.25)
            return DetectionResult(
                detector=self.name,
                detected=True,
                threat_level=ThreatLevel.ATTACK,
                attack_type=AttackType.FAKE_SPEED,
                severity=Severity.CRITICAL if extreme else Severity.HIGH,
                confidence=round(confidence, 4),
                can_id=message.arbitration_id,
                timestamp=message.timestamp,
                description=(
                    f"Forged vehicle speed: {speed:.1f} km/h reported on "
                    f"{message.can_id_hex}, above the {config.fake_speed_threshold:.0f} km/h "
                    f"attack threshold"
                ),
                evidence={
                    **base_evidence,
                    "threshold_kmh": config.fake_speed_threshold,
                    "exceeded_by_kmh": round(excess, 2),
                    "rule": "speed_above_attack_threshold",
                },
            )

        # --- 2. Kinematics ----------------------------------------------
        if acceleration is not None and abs(acceleration) > config.fake_speed_max_acceleration:
            ratio = abs(acceleration) / max(config.fake_speed_max_acceleration, 0.1)
            attack = ratio >= 3.0
            return DetectionResult(
                detector=self.name,
                detected=True,
                threat_level=ThreatLevel.ATTACK if attack else ThreatLevel.SUSPICIOUS,
                attack_type=AttackType.FAKE_SPEED,
                severity=Severity.HIGH if attack else Severity.MEDIUM,
                confidence=round(min(1.0, 0.45 + ratio * 0.12), 4),
                can_id=message.arbitration_id,
                timestamp=message.timestamp,
                description=(
                    f"Physically impossible speed change: {previous_speed:.1f} -> "
                    f"{speed:.1f} km/h ({acceleration:+.1f} km/h/s, limit "
                    f"{config.fake_speed_max_acceleration:.1f})"
                ),
                evidence={
                    **base_evidence,
                    "max_acceleration_kmh_per_s": config.fake_speed_max_acceleration,
                    "rule": "implausible_acceleration",
                },
            )

        # --- 3. Elevated but not yet an attack ---------------------------
        if speed >= config.fake_speed_suspicious_threshold:
            span = max(config.fake_speed_threshold - config.fake_speed_suspicious_threshold, 1.0)
            progress = (speed - config.fake_speed_suspicious_threshold) / span
            return DetectionResult(
                detector=self.name,
                detected=True,
                threat_level=ThreatLevel.SUSPICIOUS,
                attack_type=AttackType.FAKE_SPEED,
                severity=Severity.MEDIUM,
                confidence=round(min(0.75, 0.35 + progress * 0.4), 4),
                can_id=message.arbitration_id,
                timestamp=message.timestamp,
                description=(
                    f"Elevated vehicle speed: {speed:.1f} km/h on {message.can_id_hex} "
                    f"(suspicious above {config.fake_speed_suspicious_threshold:.0f} km/h)"
                ),
                evidence={
                    **base_evidence,
                    "threshold_kmh": config.fake_speed_suspicious_threshold,
                    "rule": "speed_above_suspicious_threshold",
                },
            )

        # Only an unflagged sample becomes the kinematic baseline. Comparing
        # against a value we already believe to be forged would raise a second
        # alert when the spoof stops, which would misreport a clean recovery.
        self._last_speed = speed
        self._last_timestamp = message.timestamp
        return self._normal(
            message,
            description=f"Vehicle speed {speed:.1f} km/h within limits",
            evidence={"observed_speed_kmh": round(speed, 2)},
        )

    # ------------------------------------------------------------------ #
    def _acceleration(self, speed: float, timestamp: float) -> float | None:
        """Rate of change in km/h per second, or ``None`` when not computable."""
        if self._last_speed is None or self._last_timestamp is None:
            return None
        delta_t = timestamp - self._last_timestamp
        if delta_t <= MIN_KINEMATIC_GAP_SECONDS or delta_t > MAX_KINEMATIC_GAP_SECONDS:
            return None
        return (speed - self._last_speed) / delta_t

    def _state_snapshot(self) -> dict[str, Any]:
        return {
            "last_speed_kmh": None if self._last_speed is None else round(self._last_speed, 2),
            "peak_speed_kmh": round(self._peak_speed, 2),
            "monitored_can_id": f"0x{self.config.speed_can_id:03X}",
        }
