"""CAN flood / bus-saturation detector.

A flood attack floods the bus with high-priority frames so that legitimate ECU
traffic loses arbitration.  Detection is purely **rate based over a rolling
time window** - never a cumulative counter, which would eventually trip on any
long-running session and could never recover.

Classification (all thresholds configurable):

===================================  =============
Observed rate                        Threat level
===================================  =============
< threshold x suspicious_ratio       NORMAL
>= threshold x suspicious_ratio      SUSPICIOUS
  and <= threshold
> threshold                          ATTACK
> threshold x critical_multiplier    ATTACK, CRITICAL
===================================  =============

A single identifier exceeding ``per_id_flood_threshold`` is reported as an
attack even when the aggregate bus rate is still below the global threshold -
that is the signature of a targeted injection against one ECU.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from app.can.message import CanMessage
from app.core.runtime_config import ConfigService
from app.detection.base import (
    AttackDetector,
    AttackType,
    DetectionResult,
    Severity,
    ThreatLevel,
)

#: Hard ceiling on retained timestamps. Time-based pruning normally keeps the
#: window far smaller; this only guards against a pathological burst.
MAX_SAMPLES = 200_000
#: Maximum number of identifiers tracked individually.
MAX_TRACKED_IDS = 4096


class FloodDetector(AttackDetector):
    """Rolling-window message-rate detector for bus flooding."""

    name = "can_flood"
    attack_type = AttackType.CAN_FLOOD
    description = (
        "Measures bus and per-identifier frame rates over a rolling time window "
        "and reports saturation attacks."
    )

    def __init__(self, config_service: ConfigService) -> None:
        super().__init__(config_service)
        self._global: deque[float] = deque()
        self._per_id: dict[int, deque[float]] = {}
        self._peak_rate: float = 0.0
        self._last_sweep: float = 0.0

    def reset(self) -> None:
        self._global.clear()
        self._per_id.clear()
        self._peak_rate = 0.0
        self._last_sweep = 0.0

    # ------------------------------------------------------------------ #
    # Window maintenance                                                 #
    # ------------------------------------------------------------------ #
    def _observe(self, timestamp: float, can_id: int, window: float) -> None:
        """Record a frame and expire everything older than the window."""
        cutoff = timestamp - window

        # An identifier that stops transmitting would otherwise keep its bucket
        # (and its stale timestamps) until the table hit its capacity limit,
        # which both wastes memory and makes top_talkers report rates for
        # identifiers that are no longer active. Sweeping once per window keeps
        # that bounded at a cost amortised across the whole window.
        if timestamp - self._last_sweep >= window:
            self._last_sweep = timestamp
            self._prune(timestamp, window)

        self._global.append(timestamp)
        while self._global and self._global[0] < cutoff:
            self._global.popleft()
        while len(self._global) > MAX_SAMPLES:  # pragma: no cover - safety valve
            self._global.popleft()

        bucket = self._per_id.get(can_id)
        if bucket is None:
            if len(self._per_id) >= MAX_TRACKED_IDS:
                self._evict_stale(cutoff)
            bucket = self._per_id.setdefault(can_id, deque())
        bucket.append(timestamp)
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        while len(bucket) > MAX_SAMPLES:  # pragma: no cover - safety valve
            bucket.popleft()

    def _evict_stale(self, cutoff: float) -> None:
        """Drop per-identifier buckets whose newest sample fell out of the window."""
        stale = [
            key for key, samples in self._per_id.items()
            if not samples or samples[-1] < cutoff
        ]
        for key in stale:
            del self._per_id[key]
        if len(self._per_id) >= MAX_TRACKED_IDS:  # pragma: no cover - extreme fan-out
            # Still full: drop the least recently active half so memory stays bounded.
            ordered = sorted(self._per_id.items(), key=lambda item: item[1][-1] if item[1] else 0.0)
            for key, _ in ordered[: len(ordered) // 2]:
                del self._per_id[key]

    def _prune(self, now: float, window: float) -> None:
        """Expire samples without recording a new one (used by rate queries)."""
        cutoff = now - window
        while self._global and self._global[0] < cutoff:
            self._global.popleft()
        for key in list(self._per_id):
            bucket = self._per_id[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if not bucket:
                del self._per_id[key]

    # ------------------------------------------------------------------ #
    # Rates                                                              #
    # ------------------------------------------------------------------ #
    def current_rate(self, now: float | None = None) -> float:
        """Aggregate bus rate in messages/second over the configured window."""
        window = self.config.flood_window_seconds
        if now is not None:
            self._prune(now, window)
        return len(self._global) / window

    def rate_for(self, can_id: int, now: float | None = None) -> float:
        """Rate in messages/second for a single identifier."""
        window = self.config.flood_window_seconds
        if now is not None:
            self._prune(now, window)
        bucket = self._per_id.get(can_id)
        return (len(bucket) / window) if bucket else 0.0

    def top_talkers(self, limit: int = 5) -> list[tuple[int, float]]:
        """The busiest identifiers in the current window."""
        window = self.config.flood_window_seconds
        ranked = sorted(
            (
                (can_id, len(samples) / window)
                for can_id, samples in self._per_id.items()
                if samples
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        return ranked[:limit]

    # ------------------------------------------------------------------ #
    # Detection                                                          #
    # ------------------------------------------------------------------ #
    def _inspect(self, message: CanMessage) -> DetectionResult:
        config = self.config
        window = config.flood_window_seconds
        self._observe(message.timestamp, message.arbitration_id, window)

        rate = len(self._global) / window
        id_rate = len(self._per_id[message.arbitration_id]) / window
        self._peak_rate = max(self._peak_rate, rate)

        suspicious_threshold = config.flood_suspicious_threshold
        critical_threshold = config.flood_threshold * config.flood_critical_multiplier
        talkers = self.top_talkers(3)

        evidence: dict[str, Any] = {
            "attack_type": AttackType.CAN_FLOOD.value,
            "observed_rate_msg_per_s": round(rate, 2),
            "threshold_msg_per_s": config.flood_threshold,
            "suspicious_threshold_msg_per_s": round(suspicious_threshold, 2),
            "window_seconds": window,
            "messages_in_window": len(self._global),
            "can_id": message.can_id_hex,
            "can_id_rate_msg_per_s": round(id_rate, 2),
            "per_id_threshold_msg_per_s": config.per_id_flood_threshold,
            "top_talkers": [
                {"can_id": f"0x{cid:03X}", "rate_msg_per_s": round(value, 2)}
                for cid, value in talkers
            ],
        }

        # --- Global saturation -------------------------------------------
        if rate > config.flood_threshold:
            critical = rate > critical_threshold
            over = rate / max(config.flood_threshold, 1e-9)
            return DetectionResult(
                detector=self.name,
                detected=True,
                threat_level=ThreatLevel.ATTACK,
                attack_type=AttackType.CAN_FLOOD,
                severity=Severity.CRITICAL if critical else Severity.HIGH,
                confidence=round(min(1.0, 0.7 + (over - 1.0) * 0.3), 4),
                can_id=message.arbitration_id,
                timestamp=message.timestamp,
                description=(
                    f"CAN flood: {rate:.0f} msg/s over a {window:g}s window, "
                    f"{over:.1f}x the {config.flood_threshold:.0f} msg/s threshold"
                ),
                evidence={
                    **evidence,
                    "rule": "global_rate_above_threshold",
                    "ratio": round(over, 2),
                },
            )

        # --- Targeted single-identifier flood ------------------------------
        if id_rate > config.per_id_flood_threshold:
            over = id_rate / max(config.per_id_flood_threshold, 1e-9)
            return DetectionResult(
                detector=self.name,
                detected=True,
                threat_level=ThreatLevel.ATTACK,
                attack_type=AttackType.CAN_FLOOD,
                severity=Severity.HIGH,
                confidence=round(min(1.0, 0.6 + (over - 1.0) * 0.3), 4),
                can_id=message.arbitration_id,
                timestamp=message.timestamp,
                description=(
                    f"Targeted flood on {message.can_id_hex}: {id_rate:.0f} msg/s, "
                    f"above the {config.per_id_flood_threshold:.0f} msg/s per-identifier threshold"
                ),
                evidence={
                    **evidence,
                    "rule": "per_id_rate_above_threshold",
                    "ratio": round(over, 2),
                },
            )

        # --- Approaching the threshold -------------------------------------
        if rate >= suspicious_threshold:
            span = max(config.flood_threshold - suspicious_threshold, 1e-9)
            progress = (rate - suspicious_threshold) / span
            return DetectionResult(
                detector=self.name,
                detected=True,
                threat_level=ThreatLevel.SUSPICIOUS,
                attack_type=AttackType.CAN_FLOOD,
                severity=Severity.MEDIUM,
                confidence=round(min(0.7, 0.3 + progress * 0.4), 4),
                can_id=message.arbitration_id,
                timestamp=message.timestamp,
                description=(
                    f"Elevated bus load: {rate:.0f} msg/s approaching the "
                    f"{config.flood_threshold:.0f} msg/s flood threshold"
                ),
                evidence={**evidence, "rule": "global_rate_above_suspicious_threshold"},
            )

        return self._normal(
            message,
            description=f"Bus rate {rate:.0f} msg/s within limits",
            evidence={
                "observed_rate_msg_per_s": round(rate, 2),
                "threshold_msg_per_s": config.flood_threshold,
                "window_seconds": window,
            },
        )

    def throttle_key(self, result: DetectionResult) -> str:
        """Bus saturation is one condition; a targeted flood is one per ID."""
        if result.evidence.get("rule") == "per_id_rate_above_threshold":
            return f"{self.name}:id:{result.can_id}"
        return f"{self.name}:bus"

    def _state_snapshot(self) -> dict[str, Any]:
        return {
            "current_rate_msg_per_s": round(self.current_rate(), 2),
            "peak_rate_msg_per_s": round(self._peak_rate, 2),
            "window_seconds": self.config.flood_window_seconds,
            "tracked_ids": len(self._per_id),
            "samples_retained": len(self._global),
        }
