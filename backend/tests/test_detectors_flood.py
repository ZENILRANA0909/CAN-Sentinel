"""CAN flood detector: rolling window, thresholds, expiry and recovery.

These tests drive the detector with explicit timestamps rather than real time,
so the window behaviour is exact and the suite stays fast.
"""

from __future__ import annotations

import pytest

from app.core.runtime_config import ConfigService
from app.detection.base import AttackType, Severity, ThreatLevel
from app.detection.flood import FloodDetector
from tests.conftest import make_message


@pytest.fixture
def config(config_service: ConfigService) -> ConfigService:
    """A small, round threshold makes the arithmetic in these tests obvious."""
    config_service.update(
        {
            "detection": {
                "flood_threshold": 100.0,
                "flood_window_seconds": 1.0,
                "flood_suspicious_ratio": 0.7,
                "flood_critical_multiplier": 3.0,
                # Equal to the global threshold, which makes the per-identifier
                # rule unreachable (an ID can never out-rate the whole bus) without
                # being invalid configuration.
                "per_id_flood_threshold": 100.0,
            }
        }
    )
    return config_service


@pytest.fixture
def detector(config: ConfigService) -> FloodDetector:
    return FloodDetector(config)


def burst(detector: FloodDetector, count: int, *, start: float, span: float = 0.9, can_id: int = 0x100):
    """Send ``count`` frames evenly spread over ``span`` seconds."""
    result = None
    step = span / max(count - 1, 1)
    for index in range(count):
        result = detector.inspect(make_message(can_id=can_id, timestamp=start + index * step))
    return result


class TestThresholds:
    def test_rate_below_suspicious_is_normal(self, detector: FloodDetector) -> None:
        # 50 frames in a 1 s window = 50 msg/s, below the 70 msg/s suspicious line.
        result = burst(detector, 50, start=1000.0)
        assert result is not None
        assert result.threat_level is ThreatLevel.NORMAL
        assert result.detected is False
        assert result.evidence["observed_rate_msg_per_s"] == pytest.approx(50.0)

    def test_rate_at_suspicious_threshold_is_suspicious(self, detector: FloodDetector) -> None:
        result = burst(detector, 70, start=1000.0)
        assert result is not None
        assert result.threat_level is ThreatLevel.SUSPICIOUS
        assert result.severity is Severity.MEDIUM
        assert result.evidence["rule"] == "global_rate_above_suspicious_threshold"

    def test_rate_exactly_at_threshold_is_suspicious_not_an_attack(
        self, detector: FloodDetector
    ) -> None:
        # The documented rule is "above the threshold", so exactly 100 msg/s is
        # the top of the suspicious band, not yet an attack.
        result = burst(detector, 100, start=1000.0)
        assert result is not None
        assert result.threat_level is ThreatLevel.SUSPICIOUS
        assert result.evidence["observed_rate_msg_per_s"] == pytest.approx(100.0)

    def test_rate_above_threshold_is_an_attack(self, detector: FloodDetector) -> None:
        result = burst(detector, 150, start=1000.0)
        assert result is not None
        assert result.threat_level is ThreatLevel.ATTACK
        assert result.attack_type is AttackType.CAN_FLOOD
        assert result.severity is Severity.HIGH
        assert result.evidence["rule"] == "global_rate_above_threshold"
        assert result.evidence["ratio"] == pytest.approx(1.5)

    def test_extreme_rate_escalates_to_critical(self, detector: FloodDetector) -> None:
        # Above 3x the threshold (the critical multiplier).
        result = burst(detector, 400, start=1000.0)
        assert result is not None
        assert result.severity is Severity.CRITICAL
        assert result.threat_level is ThreatLevel.ATTACK


class TestBurstsAndWindow:
    def test_tight_burst_is_detected(self, detector: FloodDetector) -> None:
        # 200 frames in 20 ms is a 200 msg/s rate over the 1 s window.
        result = burst(detector, 200, start=1000.0, span=0.02)
        assert result is not None
        assert result.threat_level is ThreatLevel.ATTACK

    def test_samples_expire_out_of_the_window(self, detector: FloodDetector) -> None:
        burst(detector, 150, start=1000.0)
        assert detector.current_rate(1000.9) == pytest.approx(150.0)

        # Five seconds later the whole burst has aged out of the window.
        assert detector.current_rate(1006.0) == pytest.approx(0.0)

    def test_returns_to_normal_after_the_window_passes(self, detector: FloodDetector) -> None:
        attack = burst(detector, 150, start=1000.0)
        assert attack is not None and attack.threat_level is ThreatLevel.ATTACK

        # Quiet period, then normal traffic resumes well after the window.
        recovered = burst(detector, 20, start=1010.0)
        assert recovered is not None
        assert recovered.threat_level is ThreatLevel.NORMAL
        assert recovered.evidence["observed_rate_msg_per_s"] == pytest.approx(20.0)

    def test_sustained_flood_stays_detected(self, detector: FloodDetector) -> None:
        for second in range(5):
            result = burst(detector, 150, start=1000.0 + second, span=0.99)
            assert result is not None
            assert result.threat_level is ThreatLevel.ATTACK


class TestPerIdentifierFlood:
    def test_targeted_flood_detected_below_the_global_threshold(
        self, config: ConfigService
    ) -> None:
        config.update({"detection": {"per_id_flood_threshold": 40.0}})
        detector = FloodDetector(config)

        # 60 msg/s on one identifier: under the 100 msg/s bus threshold, but
        # over the 40 msg/s per-identifier threshold.
        result = burst(detector, 60, start=1000.0, can_id=0x123)
        assert result is not None
        assert result.threat_level is ThreatLevel.ATTACK
        assert result.evidence["rule"] == "per_id_rate_above_threshold"
        assert result.can_id == 0x123

    def test_rate_for_identifier_is_tracked_separately(self, detector: FloodDetector) -> None:
        burst(detector, 30, start=1000.0, can_id=0x100)
        burst(detector, 10, start=1000.0, can_id=0x200)
        assert detector.rate_for(0x100) == pytest.approx(30.0)
        assert detector.rate_for(0x200) == pytest.approx(10.0)
        assert detector.rate_for(0x999) == 0.0

    def test_top_talkers_ranks_by_rate(self, detector: FloodDetector) -> None:
        burst(detector, 30, start=1000.0, can_id=0x100)
        burst(detector, 10, start=1000.0, can_id=0x200)
        talkers = detector.top_talkers(2)
        assert talkers[0][0] == 0x100
        assert talkers[1][0] == 0x200


class TestMemoryBounds:
    def test_window_does_not_grow_without_limit(self, detector: FloodDetector) -> None:
        """A long run must not accumulate state: this is the bug a naive
        cumulative counter would have."""
        for second in range(200):
            burst(detector, 20, start=1000.0 + second, span=0.9)

        state = detector.snapshot()["state"]
        # Only the current window's samples are retained, not 200 seconds' worth.
        assert state["samples_retained"] <= 40
        assert state["tracked_ids"] <= 2

    def test_identifier_table_is_pruned(self, detector: FloodDetector) -> None:
        for index in range(500):
            detector.inspect(make_message(can_id=0x100 + (index % 300), timestamp=1000.0 + index * 0.001))
        # Every identifier is still inside the window here.
        assert detector.snapshot()["state"]["tracked_ids"] <= 300

        # Long after the window, a single new frame prunes the stale entries.
        detector.inspect(make_message(can_id=0x7FF, timestamp=2000.0))
        assert detector.snapshot()["state"]["tracked_ids"] == 1

    def test_reset_clears_everything(self, detector: FloodDetector) -> None:
        burst(detector, 150, start=1000.0)
        detector.reset()
        state = detector.snapshot()["state"]
        assert state["samples_retained"] == 0
        assert state["tracked_ids"] == 0
        assert state["peak_rate_msg_per_s"] == 0.0


class TestConfigurability:
    def test_window_change_applies_immediately(self, detector: FloodDetector, config: ConfigService) -> None:
        burst(detector, 90, start=1000.0, span=0.9)
        assert detector.current_rate(1000.9) == pytest.approx(90.0)

        # Doubling the window halves the measured rate for the same traffic.
        config.update({"detection": {"flood_window_seconds": 2.0}})
        assert detector.current_rate(1000.9) == pytest.approx(45.0)

    def test_threshold_change_flips_the_verdict(self, detector: FloodDetector, config: ConfigService) -> None:
        result = burst(detector, 50, start=1000.0)
        assert result is not None and result.threat_level is ThreatLevel.NORMAL

        config.update({"detection": {"flood_threshold": 10.0, "per_id_flood_threshold": 10.0}})
        result = burst(detector, 50, start=1010.0)
        assert result is not None and result.threat_level is ThreatLevel.ATTACK
