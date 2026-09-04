"""Unexpected-identifier detector.

A production vehicle bus is a closed system: the set of arbitration IDs that
can legitimately appear is fixed by the vehicle's network design.  An
identifier outside that set means something is transmitting that should not be
- an aftermarket dongle, a compromised ECU, or an attacker's tool.

A single unexpected frame is SUSPICIOUS (it may be a one-off glitch); an
identifier that keeps reappearing inside the observation window is escalated
to ATTACK, because sustained transmission indicates an active injector rather
than bus noise.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from app.can.message import CanMessage
from app.can.signals import describe_can_id
from app.core.runtime_config import ConfigService
from app.detection.base import (
    AttackDetector,
    AttackType,
    DetectionResult,
    Severity,
    ThreatLevel,
)

#: Maximum number of distinct unexpected identifiers tracked at once.
MAX_TRACKED_UNKNOWN_IDS = 2048
#: Per-identifier cap on retained sighting timestamps.
MAX_SIGHTINGS_PER_ID = 5000
#: Diagnostic identifiers are legitimate but noteworthy on a moving vehicle.
DIAGNOSTIC_IDS = frozenset({0x7DF, *range(0x7E0, 0x7E8), *range(0x7E8, 0x7F0)})


class IdAnomalyDetector(AttackDetector):
    """Detect CAN identifiers outside the configured allowlist."""

    name = "id_anomaly"
    attack_type = AttackType.ID_ANOMALY
    description = (
        "Reports arbitration IDs that are not part of the vehicle's known "
        "network design, escalating identifiers that persist."
    )

    def __init__(self, config_service: ConfigService) -> None:
        super().__init__(config_service)
        self._sightings: dict[int, deque[float]] = {}
        self._first_seen: dict[int, float] = {}
        self._total_unknown_frames = 0

    def reset(self) -> None:
        self._sightings.clear()
        self._first_seen.clear()
        self._total_unknown_frames = 0

    @property
    def unknown_ids(self) -> list[int]:
        """Identifiers currently regarded as unexpected."""
        return sorted(self._sightings)

    # ------------------------------------------------------------------ #
    def _inspect(self, message: CanMessage) -> DetectionResult:
        config = self.config
        allowlist = config.allowed_can_id_set

        if not allowlist:
            # With no allowlist there is no notion of "unexpected"; say so
            # explicitly rather than silently reporting everything as clean.
            return self._normal(
                message,
                description="Identifier allowlist is empty - detector inactive",
                evidence={"allowlist_size": 0},
            )

        can_id = message.arbitration_id
        if can_id in allowlist:
            return self._normal(
                message, description=f"{message.can_id_hex} is an expected identifier"
            )

        now = message.timestamp
        window = config.id_anomaly_window_seconds
        count = self._record(can_id, now, window)
        self._total_unknown_frames += 1

        evidence: dict[str, Any] = {
            "attack_type": AttackType.ID_ANOMALY.value,
            "can_id": message.can_id_hex,
            "can_id_decimal": can_id,
            "is_extended_id": message.is_extended_id,
            "dlc": message.dlc,
            "payload": message.data_hex,
            "sightings_in_window": count,
            "window_seconds": window,
            "escalation_count": config.id_anomaly_escalation_count,
            "allowlist_size": len(allowlist),
            "first_seen": self._first_seen.get(can_id),
            "known_label": describe_can_id(can_id),
            "is_diagnostic_range": can_id in DIAGNOSTIC_IDS,
        }

        if count >= config.id_anomaly_escalation_count:
            ratio = count / max(config.id_anomaly_escalation_count, 1)
            critical = ratio >= 5.0
            return DetectionResult(
                detector=self.name,
                detected=True,
                threat_level=ThreatLevel.ATTACK,
                attack_type=AttackType.ID_ANOMALY,
                severity=Severity.CRITICAL if critical else Severity.HIGH,
                confidence=round(min(1.0, 0.65 + (ratio - 1.0) * 0.1), 4),
                can_id=can_id,
                timestamp=now,
                description=(
                    f"Unauthorised identifier {message.can_id_hex} transmitting persistently: "
                    f"{count} frames in {window:g}s"
                ),
                evidence={**evidence, "rule": "unknown_id_persistent"},
            )

        return DetectionResult(
            detector=self.name,
            detected=True,
            threat_level=ThreatLevel.SUSPICIOUS,
            attack_type=AttackType.ID_ANOMALY,
            severity=Severity.MEDIUM,
            confidence=round(min(0.6, 0.3 + count * 0.06), 4),
            can_id=can_id,
            timestamp=now,
            description=(
                f"Unexpected identifier {message.can_id_hex} observed "
                f"({count} frame(s) in {window:g}s); not in the allowlist"
            ),
            evidence={**evidence, "rule": "unknown_id_observed"},
        )

    # ------------------------------------------------------------------ #
    def _record(self, can_id: int, now: float, window: float) -> int:
        """Record a sighting and return the count inside the rolling window."""
        bucket = self._sightings.get(can_id)
        if bucket is None:
            if len(self._sightings) >= MAX_TRACKED_UNKNOWN_IDS:
                self._evict(now - window)
            bucket = self._sightings.setdefault(can_id, deque())
            self._first_seen[can_id] = now
        bucket.append(now)
        cutoff = now - window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        while len(bucket) > MAX_SIGHTINGS_PER_ID:  # pragma: no cover - safety valve
            bucket.popleft()
        return len(bucket)

    def _evict(self, cutoff: float) -> None:
        stale = [
            key for key, samples in self._sightings.items()
            if not samples or samples[-1] < cutoff
        ]
        for key in stale:
            self._sightings.pop(key, None)
            self._first_seen.pop(key, None)
        if len(self._sightings) >= MAX_TRACKED_UNKNOWN_IDS:  # pragma: no cover
            ordered = sorted(
                self._sightings.items(), key=lambda item: item[1][-1] if item[1] else 0.0
            )
            for key, _ in ordered[: len(ordered) // 2]:
                self._sightings.pop(key, None)
                self._first_seen.pop(key, None)

    def _state_snapshot(self) -> dict[str, Any]:
        return {
            "allowlist_size": len(self.config.allowed_can_id_set),
            "unknown_ids_tracked": len(self._sightings),
            "unknown_ids": [f"0x{cid:03X}" for cid in sorted(self._sightings)[:32]],
            "total_unknown_frames": self._total_unknown_frames,
        }
