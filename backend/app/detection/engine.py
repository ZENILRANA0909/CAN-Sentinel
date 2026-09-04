"""Detection engine.

The engine owns the detector set, runs every detector against every frame and
decides which verdicts are worth turning into a persisted, broadcast security
event.

That last step matters.  Under a 2000 msg/s flood the flood detector produces a
verdict 2000 times a second; writing 2000 rows a second and pushing 2000
WebSocket frames would turn the monitor into the denial of service it is meant
to observe.  :class:`EventThrottler` collapses a continuing condition into one
event per cooldown period, carries the suppressed count in the evidence, and
still emits immediately when the severity escalates - so a flood that gets
worse is never hidden behind a cooldown.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.can.message import CanMessage
from app.core.logging import get_logger
from app.core.runtime_config import ConfigService
from app.detection.base import (
    AttackDetector,
    AttackType,
    DetectionResult,
    Severity,
    ThreatLevel,
    severity_rank,
)
from app.detection.fake_speed import FakeSpeedDetector
from app.detection.flood import FloodDetector
from app.detection.frequency import FrequencyAnomalyDetector
from app.detection.id_anomaly import IdAnomalyDetector

logger = get_logger("detection.engine")

#: Throttle bookkeeping older than this multiple of the cooldown is discarded.
THROTTLE_PRUNE_FACTOR = 20.0
MAX_THROTTLE_KEYS = 8192


@dataclass
class _ThrottleState:
    last_emitted: float
    last_severity: int
    suppressed: int = 0


class EventThrottler:
    """Collapse a persistent condition into periodic, escalation-aware events."""

    def __init__(self) -> None:
        self._state: dict[str, _ThrottleState] = {}

    def should_emit(
        self, key: str, severity: Severity, now: float, cooldown: float
    ) -> tuple[bool, int]:
        """Return ``(emit, suppressed_since_last_emit)``."""
        rank = severity_rank(severity)
        state = self._state.get(key)
        if state is None:
            self._admit(key, now, rank)
            return True, 0
        escalated = rank > state.last_severity
        elapsed = now - state.last_emitted
        if escalated or elapsed >= cooldown:
            suppressed = state.suppressed
            state.last_emitted = now
            state.last_severity = rank
            state.suppressed = 0
            return True, suppressed
        state.suppressed += 1
        return False, state.suppressed

    def _admit(self, key: str, now: float, rank: int) -> None:
        if len(self._state) >= MAX_THROTTLE_KEYS:  # pragma: no cover - extreme fan-out
            oldest = sorted(self._state.items(), key=lambda item: item[1].last_emitted)
            for stale_key, _ in oldest[: len(oldest) // 2]:
                del self._state[stale_key]
        self._state[key] = _ThrottleState(last_emitted=now, last_severity=rank)

    def prune(self, now: float, cooldown: float) -> int:
        """Drop bookkeeping for conditions that have not recurred."""
        horizon = max(cooldown, 1.0) * THROTTLE_PRUNE_FACTOR
        stale = [key for key, state in self._state.items() if now - state.last_emitted > horizon]
        for key in stale:
            del self._state[key]
        return len(stale)

    def reset(self) -> None:
        self._state.clear()

    def __len__(self) -> int:
        return len(self._state)


@dataclass
class AnalysisOutcome:
    """Everything the pipeline needs to know about one analysed frame."""

    message: CanMessage
    results: list[DetectionResult] = field(default_factory=list)
    reportable: list[DetectionResult] = field(default_factory=list)
    threat_level: ThreatLevel = ThreatLevel.NORMAL
    severity: Severity = Severity.INFO

    @property
    def detected(self) -> bool:
        return self.threat_level is not ThreatLevel.NORMAL

    @property
    def attack_types(self) -> list[AttackType]:
        return [result.attack_type for result in self.results if result.detected]

    @property
    def worst(self) -> DetectionResult | None:
        """The highest-severity verdict for this frame, if any fired."""
        firing = [result for result in self.results if result.detected]
        if not firing:
            return None
        return max(firing, key=lambda result: (result.severity_rank, result.confidence))


class DetectionEngine:
    """Runs the configured detectors over the frame stream."""

    def __init__(
        self, config_service: ConfigService, detectors: list[AttackDetector] | None = None
    ) -> None:
        self._config_service = config_service
        self.detectors: list[AttackDetector] = (
            detectors if detectors is not None else build_default_detectors(config_service)
        )
        self._throttler = EventThrottler()
        self._analysed = 0
        self._flagged = 0
        self._emitted = 0
        self._suppressed = 0
        self._by_attack_type: Counter[str] = Counter()
        self._by_severity: Counter[str] = Counter()
        self._last_prune = time.monotonic()

    # ------------------------------------------------------------------ #
    # Analysis                                                           #
    # ------------------------------------------------------------------ #
    def analyze(self, message: CanMessage) -> AnalysisOutcome:
        """Run every detector over ``message`` and decide what to report."""
        outcome = AnalysisOutcome(message=message)
        config = self._config_service.detection
        if not config.enabled:
            return outcome

        self._analysed += 1
        cooldown = config.event_cooldown_seconds

        for detector in self.detectors:
            try:
                result = detector.inspect(message)
            except Exception as exc:
                # One misbehaving detector must never stop the others or the
                # pipeline; log it and carry on.
                logger.error(
                    "Detector raised an exception",
                    exc_info=True,
                    extra={"context": {"detector": detector.name, "error": str(exc)}},
                )
                continue

            outcome.results.append(result)
            if not result.detected:
                continue

            self._flagged += 1
            if severity_rank(result.severity) > severity_rank(outcome.severity):
                outcome.severity = result.severity
            if result.threat_level is ThreatLevel.ATTACK:
                outcome.threat_level = ThreatLevel.ATTACK
            elif outcome.threat_level is ThreatLevel.NORMAL:
                outcome.threat_level = result.threat_level

            emit, suppressed = self._throttler.should_emit(
                detector.throttle_key(result), result.severity, message.timestamp, cooldown
            )
            if emit:
                self._emitted += 1
                self._by_attack_type[result.attack_type.value] += 1
                self._by_severity[result.severity.value] += 1
                if suppressed:
                    result = result.model_copy(
                        update={
                            "evidence": {
                                **result.evidence,
                                "suppressed_since_last_event": suppressed,
                            }
                        }
                    )
                outcome.reportable.append(result)
            else:
                self._suppressed += 1

        self._maybe_prune(cooldown)
        return outcome

    def _maybe_prune(self, cooldown: float) -> None:
        now = time.monotonic()
        if now - self._last_prune < 30.0:
            return
        self._last_prune = now
        self._throttler.prune(time.time(), cooldown)

    # ------------------------------------------------------------------ #
    # Lifecycle & introspection                                          #
    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        """Clear detector state and throttling, but keep lifetime counters."""
        for detector in self.detectors:
            detector.reset()
        self._throttler.reset()

    def reset_statistics(self) -> None:
        self._analysed = 0
        self._flagged = 0
        self._emitted = 0
        self._suppressed = 0
        self._by_attack_type.clear()
        self._by_severity.clear()

    def get_detector(self, name: str) -> AttackDetector | None:
        for detector in self.detectors:
            if detector.name == name:
                return detector
        return None

    @property
    def flood_detector(self) -> FloodDetector | None:
        detector = self.get_detector(FloodDetector.name)
        return detector if isinstance(detector, FloodDetector) else None

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self._config_service.detection.enabled,
            "analysed_messages": self._analysed,
            "flagged_verdicts": self._flagged,
            "events_emitted": self._emitted,
            "events_suppressed": self._suppressed,
            "throttle_keys": len(self._throttler),
            "by_attack_type": dict(self._by_attack_type),
            "by_severity": dict(self._by_severity),
            "detectors": [detector.snapshot() for detector in self.detectors],
        }


def build_default_detectors(config_service: ConfigService) -> list[AttackDetector]:
    """The detector set enabled by default, in evaluation order."""
    return [
        FakeSpeedDetector(config_service),
        FloodDetector(config_service),
        IdAnomalyDetector(config_service),
        FrequencyAnomalyDetector(config_service),
    ]
