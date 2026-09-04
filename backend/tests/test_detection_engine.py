"""Detection engine: aggregation, throttling and fault isolation."""

from __future__ import annotations

import pytest

from app.can.message import CanMessage
from app.core.runtime_config import ConfigService
from app.detection.base import (
    AttackDetector,
    AttackType,
    DetectionResult,
    Severity,
    ThreatLevel,
)
from app.detection.engine import DetectionEngine, EventThrottler
from tests.conftest import make_message, make_speed_message


class TestThrottler:
    def test_first_occurrence_is_always_emitted(self) -> None:
        throttler = EventThrottler()
        emit, suppressed = throttler.should_emit("k", Severity.HIGH, now=100.0, cooldown=2.0)
        assert emit is True
        assert suppressed == 0

    def test_repeat_inside_cooldown_is_suppressed(self) -> None:
        throttler = EventThrottler()
        throttler.should_emit("k", Severity.HIGH, now=100.0, cooldown=2.0)
        emit, _ = throttler.should_emit("k", Severity.HIGH, now=100.5, cooldown=2.0)
        assert emit is False

    def test_emits_again_after_the_cooldown(self) -> None:
        throttler = EventThrottler()
        throttler.should_emit("k", Severity.HIGH, now=100.0, cooldown=2.0)
        for offset in (0.5, 1.0, 1.5):
            throttler.should_emit("k", Severity.HIGH, now=100.0 + offset, cooldown=2.0)
        emit, suppressed = throttler.should_emit("k", Severity.HIGH, now=102.0, cooldown=2.0)
        assert emit is True
        assert suppressed == 3

    def test_escalation_bypasses_the_cooldown(self) -> None:
        """A worsening attack must never be hidden behind a cooldown."""
        throttler = EventThrottler()
        throttler.should_emit("k", Severity.MEDIUM, now=100.0, cooldown=60.0)
        emit, _ = throttler.should_emit("k", Severity.CRITICAL, now=100.1, cooldown=60.0)
        assert emit is True

    def test_de_escalation_does_not_bypass_the_cooldown(self) -> None:
        throttler = EventThrottler()
        throttler.should_emit("k", Severity.CRITICAL, now=100.0, cooldown=60.0)
        emit, _ = throttler.should_emit("k", Severity.LOW, now=100.1, cooldown=60.0)
        assert emit is False

    def test_distinct_keys_are_independent(self) -> None:
        throttler = EventThrottler()
        assert throttler.should_emit("a", Severity.HIGH, now=100.0, cooldown=60.0)[0] is True
        assert throttler.should_emit("b", Severity.HIGH, now=100.0, cooldown=60.0)[0] is True

    def test_prune_drops_inactive_keys(self) -> None:
        throttler = EventThrottler()
        throttler.should_emit("k", Severity.HIGH, now=100.0, cooldown=2.0)
        assert len(throttler) == 1
        throttler.prune(now=100_000.0, cooldown=2.0)
        assert len(throttler) == 0


class TestEngineAggregation:
    def test_clean_traffic_produces_no_events(self, engine: DetectionEngine) -> None:
        outcome = engine.analyze(make_speed_message(60.0, 1000.0))
        assert outcome.detected is False
        assert outcome.threat_level is ThreatLevel.NORMAL
        assert outcome.reportable == []
        # Every detector still returns an explicit verdict.
        assert len(outcome.results) == 4

    def test_reports_the_worst_severity_across_detectors(self, engine: DetectionEngine) -> None:
        outcome = engine.analyze(make_speed_message(255.0, 1000.0))
        assert outcome.threat_level is ThreatLevel.ATTACK
        assert outcome.severity is Severity.HIGH
        assert AttackType.FAKE_SPEED in outcome.attack_types

    def test_worst_returns_the_highest_severity_verdict(self, engine: DetectionEngine) -> None:
        outcome = engine.analyze(make_speed_message(255.0, 1000.0))
        worst = outcome.worst
        assert worst is not None
        assert worst.attack_type is AttackType.FAKE_SPEED

    def test_multiple_detectors_can_fire_on_one_frame(self, engine: DetectionEngine) -> None:
        # An unknown identifier carrying a speed-frame payload is flagged by the
        # identifier detector; the speed detector ignores it.
        outcome = engine.analyze(make_message(can_id=0x123, timestamp=1000.0, data=b"\xff" * 8))
        assert AttackType.ID_ANOMALY in outcome.attack_types

    def test_disabled_engine_produces_nothing(
        self, engine: DetectionEngine, config_service: ConfigService
    ) -> None:
        config_service.update({"detection": {"enabled": False}})
        outcome = engine.analyze(make_speed_message(255.0, 1000.0))
        assert outcome.results == []
        assert outcome.detected is False


class TestEngineThrottling:
    def test_sustained_attack_is_collapsed_into_periodic_events(
        self, config_service: ConfigService
    ) -> None:
        config_service.update({"detection": {"event_cooldown_seconds": 2.0}})
        engine = DetectionEngine(config_service)

        emitted = 0
        for index in range(100):
            outcome = engine.analyze(make_speed_message(255.0, 1000.0 + index * 0.02))
            emitted += len(
                [r for r in outcome.reportable if r.attack_type is AttackType.FAKE_SPEED]
            )

        # Two seconds of spoofing at 50 Hz is 100 verdicts but only one event.
        assert emitted == 1
        snapshot = engine.snapshot()
        assert snapshot["events_suppressed"] > 50

    def test_suppressed_count_is_carried_in_the_evidence(
        self, config_service: ConfigService
    ) -> None:
        config_service.update({"detection": {"event_cooldown_seconds": 1.0}})
        engine = DetectionEngine(config_service)

        reported: list[DetectionResult] = []
        for index in range(200):
            outcome = engine.analyze(make_speed_message(255.0, 1000.0 + index * 0.02))
            reported.extend(
                r for r in outcome.reportable if r.attack_type is AttackType.FAKE_SPEED
            )

        assert len(reported) >= 2
        assert reported[1].evidence["suppressed_since_last_event"] > 0

    def test_zero_cooldown_reports_everything(self, config_service: ConfigService) -> None:
        config_service.update({"detection": {"event_cooldown_seconds": 0.0}})
        engine = DetectionEngine(config_service)
        emitted = sum(
            len([r for r in engine.analyze(make_speed_message(255.0, 1000.0 + i * 0.02)).reportable
                 if r.attack_type is AttackType.FAKE_SPEED])
            for i in range(10)
        )
        assert emitted == 10


class TestFaultIsolation:
    def test_a_failing_detector_does_not_stop_the_others(
        self, config_service: ConfigService
    ) -> None:
        class ExplodingDetector(AttackDetector):
            name = "exploding"
            attack_type = AttackType.NONE

            def _inspect(self, message: CanMessage) -> DetectionResult:
                raise RuntimeError("detector bug")

            def reset(self) -> None:
                return None

        from app.detection.fake_speed import FakeSpeedDetector

        engine = DetectionEngine(
            config_service,
            detectors=[ExplodingDetector(config_service), FakeSpeedDetector(config_service)],
        )
        outcome = engine.analyze(make_speed_message(255.0, 1000.0))

        # The healthy detector still produced its verdict.
        assert outcome.threat_level is ThreatLevel.ATTACK
        assert len(outcome.results) == 1
        assert outcome.results[0].detector == "fake_speed"


class TestEngineLifecycle:
    def test_default_detector_set(self, engine: DetectionEngine) -> None:
        names = {detector.name for detector in engine.detectors}
        assert names == {"fake_speed", "can_flood", "id_anomaly", "frequency_anomaly"}

    def test_get_detector_by_name(self, engine: DetectionEngine) -> None:
        assert engine.get_detector("can_flood") is not None
        assert engine.get_detector("nonexistent") is None
        assert engine.flood_detector is not None

    def test_reset_clears_detector_state_but_keeps_counters(self, engine: DetectionEngine) -> None:
        engine.analyze(make_speed_message(255.0, 1000.0))
        assert engine.snapshot()["analysed_messages"] == 1
        engine.reset()
        assert engine.snapshot()["analysed_messages"] == 1
        assert engine.flood_detector is not None
        assert engine.flood_detector.snapshot()["state"]["samples_retained"] == 0

    def test_reset_statistics_clears_counters(self, engine: DetectionEngine) -> None:
        engine.analyze(make_speed_message(255.0, 1000.0))
        engine.reset_statistics()
        snapshot = engine.snapshot()
        assert snapshot["analysed_messages"] == 0
        assert snapshot["events_emitted"] == 0
        assert snapshot["by_attack_type"] == {}

    def test_snapshot_reports_every_detector(self, engine: DetectionEngine) -> None:
        snapshot = engine.snapshot()
        assert len(snapshot["detectors"]) == 4
        for detector in snapshot["detectors"]:
            assert {"name", "attack_type", "description", "enabled", "state"} <= detector.keys()

    def test_flood_throttle_key_is_bus_wide(self, engine: DetectionEngine) -> None:
        """A bus-wide flood must not emit one event per identifier."""
        flood = engine.flood_detector
        assert flood is not None
        result = DetectionResult(
            detector="can_flood",
            detected=True,
            threat_level=ThreatLevel.ATTACK,
            attack_type=AttackType.CAN_FLOOD,
            severity=Severity.HIGH,
            confidence=0.9,
            can_id=0x123,
            timestamp=1000.0,
            description="",
            evidence={"rule": "global_rate_above_threshold"},
        )
        assert flood.throttle_key(result) == "can_flood:bus"

        targeted = result.model_copy(update={"evidence": {"rule": "per_id_rate_above_threshold"}})
        assert flood.throttle_key(targeted) == "can_flood:id:291"


class TestDetectionResult:
    def test_normal_factory_is_explicit(self) -> None:
        result = DetectionResult.normal(detector="d", timestamp=1.0, can_id=0x100)
        assert result.detected is False
        assert result.threat_level is ThreatLevel.NORMAL
        assert result.attack_type is AttackType.NONE
        assert result.severity is Severity.INFO
        assert result.confidence == 0.0

    def test_confidence_is_bounded(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DetectionResult(
                detector="d",
                detected=True,
                threat_level=ThreatLevel.ATTACK,
                attack_type=AttackType.FAKE_SPEED,
                severity=Severity.HIGH,
                confidence=1.5,
                timestamp=1.0,
                description="",
            )

    def test_to_wire_is_json_safe(self) -> None:
        import json

        result = DetectionResult.normal(detector="d", timestamp=1.0, can_id=0x300)
        json.dumps(result.to_wire())
        assert result.to_wire()["can_id_hex"] == "0x300"
