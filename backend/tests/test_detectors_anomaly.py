"""Identifier-anomaly and frequency-anomaly detectors."""

from __future__ import annotations

import pytest

from app.can.message import CanMessage
from app.core.runtime_config import ConfigService
from app.detection.base import AttackType, Severity, ThreatLevel
from app.detection.frequency import FrequencyAnomalyDetector
from app.detection.id_anomaly import IdAnomalyDetector
from tests.conftest import make_message


# --------------------------------------------------------------------------- #
# Identifier anomaly                                                          #
# --------------------------------------------------------------------------- #
@pytest.fixture
def id_detector(config_service: ConfigService) -> IdAnomalyDetector:
    return IdAnomalyDetector(config_service)


class TestIdAnomalyDetector:
    def test_allowlisted_identifier_is_normal(self, id_detector: IdAnomalyDetector) -> None:
        result = id_detector.inspect(make_message(can_id=0x100, timestamp=1000.0))
        assert result.threat_level is ThreatLevel.NORMAL
        assert result.detected is False

    @pytest.mark.parametrize("can_id", [0x100, 0x200, 0x300, 0x400, 0x500, 0x600, 0x700])
    def test_every_catalogued_identifier_is_allowed(
        self, id_detector: IdAnomalyDetector, can_id: int
    ) -> None:
        assert id_detector.inspect(make_message(can_id=can_id, timestamp=1000.0)).detected is False

    def test_unknown_identifier_is_suspicious_on_first_sighting(
        self, id_detector: IdAnomalyDetector
    ) -> None:
        result = id_detector.inspect(make_message(can_id=0x123, timestamp=1000.0))
        assert result.threat_level is ThreatLevel.SUSPICIOUS
        assert result.attack_type is AttackType.ID_ANOMALY
        assert result.severity is Severity.MEDIUM
        assert result.evidence["rule"] == "unknown_id_observed"
        assert result.evidence["can_id"] == "0x123"
        assert result.evidence["sightings_in_window"] == 1

    def test_persistent_unknown_identifier_escalates_to_attack(
        self, id_detector: IdAnomalyDetector
    ) -> None:
        # Default escalation count is 5 sightings inside the window.
        result = None
        for index in range(5):
            result = id_detector.inspect(make_message(can_id=0x123, timestamp=1000.0 + index * 0.1))
        assert result is not None
        assert result.threat_level is ThreatLevel.ATTACK
        assert result.severity is Severity.HIGH
        assert result.evidence["rule"] == "unknown_id_persistent"

    def test_heavy_injection_escalates_to_critical(self, id_detector: IdAnomalyDetector) -> None:
        result = None
        for index in range(30):
            result = id_detector.inspect(make_message(can_id=0x000, timestamp=1000.0 + index * 0.01))
        assert result is not None
        assert result.severity is Severity.CRITICAL

    def test_sightings_expire_so_the_detector_de_escalates(
        self, id_detector: IdAnomalyDetector
    ) -> None:
        for index in range(6):
            id_detector.inspect(make_message(can_id=0x123, timestamp=1000.0 + index * 0.1))

        # Well beyond the 5 s window: the count restarts, so a lone later frame
        # is suspicious again rather than still an attack.
        later = id_detector.inspect(make_message(can_id=0x123, timestamp=1100.0))
        assert later.threat_level is ThreatLevel.SUSPICIOUS
        assert later.evidence["sightings_in_window"] == 1

    def test_empty_allowlist_disables_the_detector(self, config_service: ConfigService) -> None:
        config_service.update({"detection": {"allowed_can_ids": []}})
        detector = IdAnomalyDetector(config_service)
        result = detector.inspect(make_message(can_id=0x123, timestamp=1000.0))
        assert result.detected is False
        assert "detector inactive" in result.description

    def test_allowlist_is_configurable(
        self, id_detector: IdAnomalyDetector, config_service: ConfigService
    ) -> None:
        assert id_detector.inspect(make_message(can_id=0x123, timestamp=1000.0)).detected is True
        config_service.update({"detection": {"allowed_can_ids": [0x123]}})
        assert id_detector.inspect(make_message(can_id=0x123, timestamp=1001.0)).detected is False

    def test_extended_identifier_is_reported(self, id_detector: IdAnomalyDetector) -> None:
        message = CanMessage(
            timestamp=1000.0, arbitration_id=0x18DAF110, is_extended_id=True, data=b"\x01"
        )
        result = id_detector.inspect(message)
        assert result.detected is True
        assert result.evidence["is_extended_id"] is True

    def test_reset_clears_tracked_identifiers(self, id_detector: IdAnomalyDetector) -> None:
        id_detector.inspect(make_message(can_id=0x123, timestamp=1000.0))
        assert id_detector.unknown_ids == [0x123]
        id_detector.reset()
        assert id_detector.unknown_ids == []


# --------------------------------------------------------------------------- #
# Frequency anomaly                                                           #
# --------------------------------------------------------------------------- #
@pytest.fixture
def freq_detector(config_service: ConfigService) -> FrequencyAnomalyDetector:
    return FrequencyAnomalyDetector(config_service)


def stream(detector: FrequencyAnomalyDetector, *, can_id: int, period: float, count: int, start: float = 1000.0):
    """Feed frames at a fixed period, returning the last verdict."""
    result = None
    for index in range(count):
        result = detector.inspect(make_message(can_id=can_id, timestamp=start + index * period))
    return result


class TestFrequencyAnomalyDetector:
    def test_collects_a_baseline_before_judging(self, freq_detector: FrequencyAnomalyDetector) -> None:
        result = stream(freq_detector, can_id=0x300, period=0.02, count=5)
        assert result is not None
        assert result.detected is False
        assert "Collecting baseline" in result.description

    def test_catalogued_period_is_normal(self, freq_detector: FrequencyAnomalyDetector) -> None:
        # 0x300 is catalogued at 20 ms.
        result = stream(freq_detector, can_id=0x300, period=0.02, count=30)
        assert result is not None
        assert result.detected is False
        assert result.evidence["expected_period_ms"] == pytest.approx(20.0)

    def test_mild_jitter_is_tolerated(self, freq_detector: FrequencyAnomalyDetector) -> None:
        # 25 ms against a 20 ms baseline: 1.25x, inside the 2.5x tolerance.
        result = stream(freq_detector, can_id=0x300, period=0.025, count=30)
        assert result is not None
        assert result.detected is False

    def test_much_faster_period_is_suspicious(self, freq_detector: FrequencyAnomalyDetector) -> None:
        # 6.7 ms against 20 ms is 3x faster: over the 2.5x flag ratio but under
        # the 5x attack ratio.
        result = stream(freq_detector, can_id=0x300, period=0.00667, count=40)
        assert result is not None
        assert result.threat_level is ThreatLevel.SUSPICIOUS
        assert result.attack_type is AttackType.FREQUENCY_ANOMALY
        assert result.evidence["rule"] == "period_too_short"

    def test_far_faster_period_is_an_attack(self, freq_detector: FrequencyAnomalyDetector) -> None:
        # 2 ms against 20 ms is 10x faster: consistent with frame injection.
        result = stream(freq_detector, can_id=0x300, period=0.002, count=40)
        assert result is not None
        assert result.threat_level is ThreatLevel.ATTACK
        assert result.severity in (Severity.HIGH, Severity.CRITICAL)
        assert result.evidence["ratio"] == pytest.approx(10.0, rel=0.1)

    def test_much_slower_period_is_suspicious(self, freq_detector: FrequencyAnomalyDetector) -> None:
        # 100 ms against 20 ms is 5x slower: frames are being suppressed.
        result = stream(freq_detector, can_id=0x300, period=0.1, count=30)
        assert result is not None
        assert result.threat_level is ThreatLevel.SUSPICIOUS
        assert result.evidence["rule"] == "period_too_long"

    def test_learns_a_baseline_for_uncatalogued_identifiers(
        self, freq_detector: FrequencyAnomalyDetector
    ) -> None:
        result = stream(freq_detector, can_id=0x321, period=0.05, count=30)
        assert result is not None
        assert result.detected is False
        assert result.evidence["baseline_source"] == "learned"
        assert result.evidence["expected_period_ms"] == pytest.approx(50.0, rel=0.05)

    def test_learned_baseline_is_frozen_against_a_later_attack(
        self, freq_detector: FrequencyAnomalyDetector
    ) -> None:
        """A detector that kept re-learning would quietly accept the attack it
        is meant to catch."""
        stream(freq_detector, can_id=0x321, period=0.05, count=30)
        result = stream(freq_detector, can_id=0x321, period=0.002, count=40, start=1100.0)
        assert result is not None
        assert result.detected is True
        assert result.evidence["expected_period_ms"] == pytest.approx(50.0, rel=0.05)

    def test_returns_to_normal_when_the_period_recovers(
        self, freq_detector: FrequencyAnomalyDetector
    ) -> None:
        attack = stream(freq_detector, can_id=0x300, period=0.002, count=40)
        assert attack is not None and attack.detected is True

        recovered = stream(freq_detector, can_id=0x300, period=0.02, count=40, start=1100.0)
        assert recovered is not None
        assert recovered.detected is False

    def test_reset_clears_learned_baselines(self, freq_detector: FrequencyAnomalyDetector) -> None:
        stream(freq_detector, can_id=0x321, period=0.05, count=30)
        assert freq_detector.snapshot()["state"]["learned_baselines"] == 1
        freq_detector.reset()
        assert freq_detector.snapshot()["state"]["learned_baselines"] == 0
        assert freq_detector.snapshot()["state"]["tracked_ids"] == 0
