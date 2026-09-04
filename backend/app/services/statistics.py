"""Live traffic and security statistics.

Everything here is in-memory and explicitly bounded.  The database holds the
full history; this service answers "what is happening right now" fast enough to
be polled by a dashboard several times a second without touching disk.
"""

from __future__ import annotations

import time
from collections import Counter, deque
from typing import Any

from app.can.message import CanMessage
from app.can.signals import describe_can_id
from app.detection.base import AttackType, Severity, ThreatLevel
from app.detection.engine import AnalysisOutcome

#: Identifiers tracked individually before the least active are folded away.
MAX_TRACKED_IDS = 2048
#: Retained points in the rate history (one per sample, ~1 s apart).
RATE_HISTORY_POINTS = 300
#: An alert counts as "active" for this long after it fires.
ACTIVE_ALERT_SECONDS = 30.0


class TrafficStatistics:
    """Rolling counters over the live frame stream."""

    def __init__(self, *, window_seconds: float = 10.0, rate_window_seconds: float = 1.0) -> None:
        self._window = max(1.0, window_seconds)
        self._rate_window = max(0.2, rate_window_seconds)
        self._samples: deque[float] = deque()
        self._by_can_id: Counter[int] = Counter()
        self._by_source: Counter[str] = Counter()
        self._flagged_by_can_id: Counter[int] = Counter()

        self._total_messages = 0
        self._total_bytes = 0
        self._flagged_messages = 0
        self._invalid_messages = 0

        self._attacks_total = 0
        self._attacks_by_type: Counter[str] = Counter()
        self._attacks_by_severity: Counter[str] = Counter()
        self._recent_attack_times: deque[tuple[float, str]] = deque()

        self._rate_history: deque[dict[str, Any]] = deque(maxlen=RATE_HISTORY_POINTS)
        self._peak_rate = 0.0
        self._started_at = time.time()
        self._last_message_at: float | None = None
        self._attacks_at_last_sample = 0

    # ------------------------------------------------------------------ #
    # Recording                                                          #
    # ------------------------------------------------------------------ #
    def record(self, message: CanMessage, outcome: AnalysisOutcome | None = None) -> None:
        """Fold one analysed frame into the counters."""
        now = message.timestamp
        self._samples.append(now)
        self._prune(now)

        self._total_messages += 1
        self._total_bytes += message.dlc
        self._last_message_at = now

        if (
            len(self._by_can_id) >= MAX_TRACKED_IDS
            and message.arbitration_id not in self._by_can_id
        ):
            self._compact_ids()
        self._by_can_id[message.arbitration_id] += 1
        self._by_source[message.source.value] += 1

        if outcome is None or not outcome.detected:
            return

        self._flagged_messages += 1
        self._flagged_by_can_id[message.arbitration_id] += 1

        for result in outcome.reportable:
            self._attacks_total += 1
            self._attacks_by_type[result.attack_type.value] += 1
            self._attacks_by_severity[result.severity.value] += 1
            self._recent_attack_times.append((result.timestamp, result.severity.value))
        self._prune_alerts(now)

    def record_invalid(self) -> None:
        """Count a frame the pipeline refused to admit."""
        self._invalid_messages += 1

    def sample(self) -> dict[str, Any]:
        """Append a point to the rate history. Called once a second."""
        now = time.time()
        self._prune(now)
        rate = self.current_rate(now)
        self._peak_rate = max(self._peak_rate, rate)
        attacks_delta = self._attacks_total - self._attacks_at_last_sample
        self._attacks_at_last_sample = self._attacks_total
        point = {
            "timestamp": now,
            "rate_msg_per_s": round(rate, 2),
            "attacks": attacks_delta,
            "total_messages": self._total_messages,
        }
        self._rate_history.append(point)
        return point

    # ------------------------------------------------------------------ #
    # Derived values                                                     #
    # ------------------------------------------------------------------ #
    def current_rate(self, now: float | None = None) -> float:
        """Messages per second over the short rate window."""
        now = now if now is not None else time.time()
        cutoff = now - self._rate_window
        count = sum(1 for stamp in reversed(self._samples) if stamp >= cutoff)
        return count / self._rate_window

    def window_rate(self, now: float | None = None) -> float:
        """Messages per second averaged over the longer statistics window."""
        now = now if now is not None else time.time()
        self._prune(now)
        return len(self._samples) / self._window

    def active_alerts(self, now: float | None = None) -> int:
        now = now if now is not None else time.time()
        self._prune_alerts(now)
        return len(self._recent_attack_times)

    def top_can_ids(self, limit: int = 10) -> list[dict[str, Any]]:
        return [
            {
                "can_id": can_id,
                "can_id_hex": f"0x{can_id:03X}",
                "label": describe_can_id(can_id),
                "count": count,
                "flagged": self._flagged_by_can_id.get(can_id, 0),
            }
            for can_id, count in self._by_can_id.most_common(limit)
        ]

    def rate_history(self, limit: int = RATE_HISTORY_POINTS) -> list[dict[str, Any]]:
        history = list(self._rate_history)
        return history[-limit:] if limit > 0 else history

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._started_at

    @property
    def total_messages(self) -> int:
        return self._total_messages

    @property
    def attacks_total(self) -> int:
        return self._attacks_total

    # ------------------------------------------------------------------ #
    # Snapshots                                                          #
    # ------------------------------------------------------------------ #
    def traffic_snapshot(self) -> dict[str, Any]:
        now = time.time()
        return {
            "total_messages": self._total_messages,
            "total_bytes": self._total_bytes,
            "invalid_messages": self._invalid_messages,
            "flagged_messages": self._flagged_messages,
            "current_rate_msg_per_s": round(self.current_rate(now), 2),
            "average_rate_msg_per_s": round(self.window_rate(now), 2),
            "peak_rate_msg_per_s": round(self._peak_rate, 2),
            "unique_can_ids": len(self._by_can_id),
            "window_seconds": self._window,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "last_message_at": self._last_message_at,
            "by_source": dict(self._by_source),
            "top_can_ids": self.top_can_ids(),
        }

    def security_snapshot(self) -> dict[str, Any]:
        now = time.time()
        by_severity = {
            level.value: self._attacks_by_severity.get(level.value, 0) for level in Severity
        }
        by_type = {
            attack.value: self._attacks_by_type.get(attack.value, 0)
            for attack in AttackType
            if attack is not AttackType.NONE
        }
        return {
            "attacks_total": self._attacks_total,
            "active_alerts": self.active_alerts(now),
            "flagged_messages": self._flagged_messages,
            "by_attack_type": by_type,
            "by_severity": by_severity,
            "threat_level": self.threat_level(now).value,
            "active_alert_window_seconds": ACTIVE_ALERT_SECONDS,
        }

    def threat_level(self, now: float | None = None) -> ThreatLevel:
        """Overall posture, derived from the severity of recent alerts."""
        now = now if now is not None else time.time()
        self._prune_alerts(now)
        if not self._recent_attack_times:
            return ThreatLevel.NORMAL
        severities = {severity for _, severity in self._recent_attack_times}
        if severities & {Severity.HIGH.value, Severity.CRITICAL.value}:
            return ThreatLevel.ATTACK
        return ThreatLevel.SUSPICIOUS

    def reset(self) -> None:
        """Clear every counter. Used by the simulator reset control."""
        self._samples.clear()
        self._by_can_id.clear()
        self._by_source.clear()
        self._flagged_by_can_id.clear()
        self._recent_attack_times.clear()
        self._rate_history.clear()
        self._attacks_by_type.clear()
        self._attacks_by_severity.clear()
        self._total_messages = 0
        self._total_bytes = 0
        self._flagged_messages = 0
        self._invalid_messages = 0
        self._attacks_total = 0
        self._attacks_at_last_sample = 0
        self._peak_rate = 0.0
        self._started_at = time.time()
        self._last_message_at = None

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #
    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        while self._samples and self._samples[0] < cutoff:
            self._samples.popleft()

    def _prune_alerts(self, now: float) -> None:
        cutoff = now - ACTIVE_ALERT_SECONDS
        while self._recent_attack_times and self._recent_attack_times[0][0] < cutoff:
            self._recent_attack_times.popleft()

    def _compact_ids(self) -> None:
        """Keep the identifier table bounded by dropping the least active half."""
        keep = dict(self._by_can_id.most_common(MAX_TRACKED_IDS // 2))
        self._by_can_id = Counter(keep)
        self._flagged_by_can_id = Counter(
            {key: value for key, value in self._flagged_by_can_id.items() if key in keep}
        )
