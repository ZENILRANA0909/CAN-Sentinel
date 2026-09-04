"""Fake Speed detector behaviour, including recovery."""

from __future__ import annotations

import pytest

from app.can.message import CanMessage
from app.core.runtime_config import ConfigService
from app.detection.base import AttackType, Severity, ThreatLevel
from app.detection.fake_speed import FakeSpeedDetector
from tests.conftest import make_speed_message


@pytest.fixture
def detector(config_service: ConfigService) -> FakeSpeedDetector:
    return FakeSpeedDetector(config_service)


def feed(detector: FakeSpeedDetector, speeds: list[float], *, start: float = 1000.0, step: float = 1.0):
    """Feed a series of speeds one second apart, returning the last verdict."""
    result = None
    for index, speed in enumerate(speeds):
        result = detector.inspect(make_speed_message(speed, start + index * step))
    return result


class TestMagnitudeRules:
    def test_normal_speed_is_normal(self, detector: FakeSpeedDetector) -> None:
        result = detector.inspect(make_speed_message(60.0, 1000.0))
        assert result.threat_level is ThreatLevel.NORMAL
        assert result.attack_type is AttackType.NONE
        assert result.detected is False
        assert result.severity is Severity.INFO

    def test_zero_speed_is_normal(self, detector: FakeSpeedDetector) -> None:
        assert detector.inspect(make_speed_message(0.0, 1000.0)).threat_level is ThreatLevel.NORMAL

    def test_speed_just_below_suspicious_threshold_is_normal(
        self, detector: FakeSpeedDetector
    ) -> None:
        # Default suspicious threshold is 120 km/h.
        assert detector.inspect(make_speed_message(119.9, 1000.0)).threat_level is ThreatLevel.NORMAL

    def test_speed_at_suspicious_threshold_is_suspicious(self, detector: FakeSpeedDetector) -> None:
        result = detector.inspect(make_speed_message(120.0, 1000.0))
        assert result.threat_level is ThreatLevel.SUSPICIOUS
        assert result.attack_type is AttackType.FAKE_SPEED
        assert result.severity is Severity.MEDIUM
        assert result.evidence["rule"] == "speed_above_suspicious_threshold"

    def test_speed_at_attack_threshold_is_still_suspicious(
        self, detector: FakeSpeedDetector
    ) -> None:
        # The rule is "above", so exactly 200 km/h has not yet crossed it.
        assert detector.inspect(make_speed_message(200.0, 1000.0)).threat_level is ThreatLevel.SUSPICIOUS

    def test_speed_above_attack_threshold_is_an_attack(self, detector: FakeSpeedDetector) -> None:
        result = detector.inspect(make_speed_message(250.0, 1000.0))
        assert result.threat_level is ThreatLevel.ATTACK
        assert result.attack_type is AttackType.FAKE_SPEED
        assert result.severity is Severity.HIGH
        assert result.evidence["observed_speed_kmh"] == pytest.approx(250.0)
        assert result.evidence["threshold_kmh"] == 200.0
        assert result.confidence > 0.7

    def test_extreme_speed_escalates_to_critical(self, detector: FakeSpeedDetector) -> None:
        # 1.5x the attack threshold escalates severity.
        result = detector.inspect(make_speed_message(320.0, 1000.0))
        assert result.severity is Severity.CRITICAL
        assert result.threat_level is ThreatLevel.ATTACK

    def test_evidence_carries_the_full_picture(self, detector: FakeSpeedDetector) -> None:
        evidence = detector.inspect(make_speed_message(250.0, 1000.0)).evidence
        assert evidence["attack_type"] == "FAKE_SPEED"
        assert evidence["can_id"] == "0x300"
        assert evidence["attack_threshold_kmh"] == 200.0
        assert evidence["exceeded_by_kmh"] == pytest.approx(50.0)


class TestOtherIdentifiers:
    def test_ignores_frames_on_other_identifiers(self, detector: FakeSpeedDetector) -> None:
        message = CanMessage(timestamp=1000.0, arbitration_id=0x100, data=b"\xff" * 8)
        result = detector.inspect(message)
        assert result.threat_level is ThreatLevel.NORMAL
        assert result.description == "Not a vehicle-speed frame"

    def test_truncated_speed_frame_is_suspicious(self, detector: FakeSpeedDetector) -> None:
        message = CanMessage(timestamp=1000.0, arbitration_id=0x300, data=b"\x01")
        result = detector.inspect(message)
        assert result.threat_level is ThreatLevel.SUSPICIOUS
        assert result.evidence["reason"] == "payload_too_short"


class TestKinematicRule:
    def test_gradual_acceleration_is_normal(self, detector: FakeSpeedDetector) -> None:
        # 5 km/h per second, well inside the 15 km/h/s plausibility limit.
        result = feed(detector, [0.0, 5.0, 10.0, 15.0, 20.0])
        assert result is not None
        assert result.threat_level is ThreatLevel.NORMAL

    def test_impossible_jump_inside_the_normal_range_is_flagged(
        self, detector: FakeSpeedDetector
    ) -> None:
        # 20 -> 119 km/h in one second is 99 km/h/s: impossible, but both values
        # are below the suspicious threshold, so only the kinematic rule can
        # catch it.
        result = feed(detector, [20.0, 119.0])
        assert result is not None
        assert result.detected is True
        assert result.attack_type is AttackType.FAKE_SPEED
        assert result.evidence["rule"] == "implausible_acceleration"
        assert result.evidence["acceleration_kmh_per_s"] == pytest.approx(99.0, abs=0.1)

    def test_large_jump_escalates_to_attack(self, detector: FakeSpeedDetector) -> None:
        result = feed(detector, [10.0, 110.0])
        assert result is not None
        assert result.threat_level is ThreatLevel.ATTACK

    def test_no_kinematic_verdict_without_a_baseline(self, detector: FakeSpeedDetector) -> None:
        result = detector.inspect(make_speed_message(100.0, 1000.0))
        assert result.threat_level is ThreatLevel.NORMAL
        assert "acceleration_kmh_per_s" not in result.evidence

    def test_long_gap_suppresses_the_kinematic_rule(self, detector: FakeSpeedDetector) -> None:
        # A ten-second gap means we simply were not observing, not that the
        # vehicle teleported.
        detector.inspect(make_speed_message(10.0, 1000.0))
        result = detector.inspect(make_speed_message(110.0, 1010.0))
        assert result.threat_level is ThreatLevel.NORMAL


class TestRecovery:
    def test_returns_to_normal_after_an_attack_stops(self, detector: FakeSpeedDetector) -> None:
        assert detector.inspect(make_speed_message(60.0, 1000.0)).threat_level is ThreatLevel.NORMAL
        attack = detector.inspect(make_speed_message(255.0, 1001.0))
        assert attack.threat_level is ThreatLevel.ATTACK

        # The spoof stops. A forged sample never becomes the kinematic
        # baseline, and the gap exceeds the kinematic window, so the return to
        # a real speed is not itself reported as an anomaly.
        recovered = detector.inspect(make_speed_message(62.0, 1005.0))
        assert recovered.threat_level is ThreatLevel.NORMAL
        assert recovered.detected is False

    def test_reset_clears_state(self, detector: FakeSpeedDetector) -> None:
        detector.inspect(make_speed_message(255.0, 1000.0))
        assert detector.snapshot()["state"]["peak_speed_kmh"] == pytest.approx(255.0)
        detector.reset()
        assert detector.snapshot()["state"]["peak_speed_kmh"] == 0.0
        assert detector.snapshot()["state"]["last_speed_kmh"] is None


class TestConfigurability:
    def test_thresholds_apply_immediately(
        self, detector: FakeSpeedDetector, config_service: ConfigService
    ) -> None:
        assert detector.inspect(make_speed_message(150.0, 1000.0)).threat_level is ThreatLevel.SUSPICIOUS

        config_service.update({"detection": {"fake_speed_threshold": 100.0,
                                             "fake_speed_suspicious_threshold": 60.0}})

        # Same speed, retuned thresholds: now an attack, with no rebuild.
        assert detector.inspect(make_speed_message(150.0, 1010.0)).threat_level is ThreatLevel.ATTACK

    def test_monitored_identifier_is_configurable(
        self, detector: FakeSpeedDetector, config_service: ConfigService
    ) -> None:
        config_service.update({"detection": {"speed_can_id": 0x400}})
        on_old_id = detector.inspect(make_speed_message(255.0, 1000.0, can_id=0x300))
        assert on_old_id.threat_level is ThreatLevel.NORMAL

        on_new_id = detector.inspect(make_speed_message(255.0, 1001.0, can_id=0x400))
        assert on_new_id.threat_level is ThreatLevel.ATTACK
