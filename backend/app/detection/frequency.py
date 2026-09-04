"""Periodic-frame frequency anomaly detector.

Most safety-relevant CAN frames are strictly periodic: the ABS module sends
vehicle speed every 20 ms, the ECM sends engine RPM every 10 ms.  Two failure
modes matter to a security monitor:

* **Too fast** - the genuine ECU is still transmitting *and* an attacker is
  injecting the same identifier, so the observed period collapses.  This is the
  signature of a spoofing attack that has not yet changed a value enough to
  trip a range check.
* **Too slow** - frames are missing.  This can mean an ECU has been silenced,
  knocked into bus-off, or is losing arbitration to a flood.

The expected period comes from the signal catalog where the identifier is
known.  For any other identifier the detector *learns* a baseline from the
first ``frequency_min_samples`` intervals and then freezes it, so that an
attack starting later cannot quietly retrain the baseline it is measured
against.

Known limitation: a frame that stops entirely produces no further frames to
inspect, so complete silence is reported by the traffic-statistics service
rather than here (see ``docs/detection.md``).
"""

from __future__ import annotations

import statistics
from collections import deque
from itertools import pairwise
from typing import Any

from app.can.message import CanMessage
from app.can.signals import expected_period_ms
from app.core.runtime_config import ConfigService
from app.detection.base import (
    AttackDetector,
    AttackType,
    DetectionResult,
    Severity,
    ThreatLevel,
)

#: Maximum identifiers tracked concurrently.
MAX_TRACKED_IDS = 4096
#: Retained arrival timestamps per identifier.
HISTORY_PER_ID = 96
#: Intervals longer than this are treated as "we stopped observing", not as a
#: missing-frame anomaly, to avoid a false alert after the monitor is paused.
MAX_MEANINGFUL_GAP_SECONDS = 5.0


def format_period(seconds: float) -> str:
    """Render a period so sub-millisecond values do not display as "0 ms"."""
    milliseconds = seconds * 1000
    if milliseconds >= 10:
        return f"{milliseconds:.0f} ms"
    if milliseconds >= 1:
        return f"{milliseconds:.1f} ms"
    return f"{milliseconds:.2f} ms"


class FrequencyAnomalyDetector(AttackDetector):
    """Detect periodic frames arriving far faster or slower than they should."""

    name = "frequency_anomaly"
    attack_type = AttackType.FREQUENCY_ANOMALY
    description = (
        "Compares the observed period of each periodic identifier against its "
        "catalogued or learned baseline."
    )

    def __init__(self, config_service: ConfigService) -> None:
        super().__init__(config_service)
        self._arrivals: dict[int, deque[float]] = {}
        self._learned_period: dict[int, float] = {}

    def reset(self) -> None:
        self._arrivals.clear()
        self._learned_period.clear()

    # ------------------------------------------------------------------ #
    def _inspect(self, message: CanMessage) -> DetectionResult:
        config = self.config
        can_id = message.arbitration_id
        now = message.timestamp

        history = self._arrivals.get(can_id)
        if history is None:
            if len(self._arrivals) >= MAX_TRACKED_IDS:
                self._evict(now)
            history = self._arrivals.setdefault(can_id, deque(maxlen=HISTORY_PER_ID))
        history.append(now)

        intervals = self._recent_intervals(history, config.frequency_min_samples)
        if len(intervals) < config.frequency_min_samples:
            return self._normal(
                message,
                description=(
                    f"Collecting baseline for {message.can_id_hex} "
                    f"({len(intervals)}/{config.frequency_min_samples} intervals)"
                ),
                evidence={"intervals_collected": len(intervals)},
            )

        observed = statistics.median(intervals)
        expected, source = self._expected_period(can_id, intervals)
        if expected is None or observed <= 0:
            return self._normal(message, description="No period baseline available")

        evidence: dict[str, Any] = {
            "attack_type": AttackType.FREQUENCY_ANOMALY.value,
            "can_id": message.can_id_hex,
            "expected_period_ms": round(expected * 1000, 3),
            "observed_period_ms": round(observed * 1000, 3),
            "expected_rate_hz": round(1.0 / expected, 2),
            "observed_rate_hz": round(1.0 / observed, 2),
            "baseline_source": source,
            "samples": len(intervals),
        }

        fast_ratio = expected / observed
        slow_ratio = observed / expected

        if fast_ratio >= config.frequency_fast_ratio:
            attack = fast_ratio >= config.frequency_attack_ratio
            critical = fast_ratio >= config.frequency_attack_ratio * 3
            return DetectionResult(
                detector=self.name,
                detected=True,
                threat_level=ThreatLevel.ATTACK if attack else ThreatLevel.SUSPICIOUS,
                attack_type=AttackType.FREQUENCY_ANOMALY,
                severity=(
                    Severity.CRITICAL if critical else Severity.HIGH if attack else Severity.MEDIUM
                ),
                confidence=round(min(1.0, 0.4 + fast_ratio * 0.08), 4),
                can_id=can_id,
                timestamp=now,
                description=(
                    f"{message.can_id_hex} arriving {fast_ratio:.1f}x faster than its "
                    f"{format_period(expected)} baseline - consistent with frame injection"
                ),
                evidence={**evidence, "rule": "period_too_short", "ratio": round(fast_ratio, 2)},
            )

        if slow_ratio >= config.frequency_slow_ratio and observed <= MAX_MEANINGFUL_GAP_SECONDS:
            return DetectionResult(
                detector=self.name,
                detected=True,
                threat_level=ThreatLevel.SUSPICIOUS,
                attack_type=AttackType.FREQUENCY_ANOMALY,
                severity=Severity.MEDIUM,
                confidence=round(min(0.75, 0.3 + slow_ratio * 0.08), 4),
                can_id=can_id,
                timestamp=now,
                description=(
                    f"{message.can_id_hex} arriving {slow_ratio:.1f}x slower than its "
                    f"{format_period(expected)} baseline - frames may be suppressed or "
                    f"losing arbitration"
                ),
                evidence={**evidence, "rule": "period_too_long", "ratio": round(slow_ratio, 2)},
            )

        return self._normal(
            message,
            description=(
                f"{message.can_id_hex} period {format_period(observed)} matches its "
                f"{format_period(expected)} baseline"
            ),
            evidence={
                "observed_period_ms": round(observed * 1000, 3),
                "expected_period_ms": round(expected * 1000, 3),
                "baseline_source": source,
            },
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _recent_intervals(history: deque[float], want: int) -> list[float]:
        """Inter-arrival times, ignoring gaps where we were not observing."""
        samples = list(history)[-(want + 1) :]
        intervals: list[float] = []
        for previous, current in pairwise(samples):
            delta = current - previous
            if 0 < delta <= MAX_MEANINGFUL_GAP_SECONDS:
                intervals.append(delta)
        return intervals

    def _expected_period(self, can_id: int, intervals: list[float]) -> tuple[float | None, str]:
        """Return the baseline period in seconds and where it came from."""
        catalogued = expected_period_ms(can_id)
        if catalogued is not None:
            return catalogued / 1000.0, "catalog"
        learned = self._learned_period.get(can_id)
        if learned is not None:
            return learned, "learned"
        # Freeze the first stable observation as this identifier's baseline.
        baseline = statistics.median(intervals)
        if baseline <= 0:  # pragma: no cover - defensive
            return None, "unavailable"
        self._learned_period[can_id] = baseline
        return baseline, "learned"

    def _evict(self, now: float) -> None:
        stale = [
            key
            for key, samples in self._arrivals.items()
            if not samples or now - samples[-1] > MAX_MEANINGFUL_GAP_SECONDS
        ]
        for key in stale:
            self._arrivals.pop(key, None)
            self._learned_period.pop(key, None)
        if len(self._arrivals) >= MAX_TRACKED_IDS:  # pragma: no cover - extreme fan-out
            ordered = sorted(
                self._arrivals.items(), key=lambda item: item[1][-1] if item[1] else 0.0
            )
            for key, _ in ordered[: len(ordered) // 2]:
                self._arrivals.pop(key, None)
                self._learned_period.pop(key, None)

    def _state_snapshot(self) -> dict[str, Any]:
        return {
            "tracked_ids": len(self._arrivals),
            "learned_baselines": len(self._learned_period),
            "min_samples": self.config.frequency_min_samples,
        }
