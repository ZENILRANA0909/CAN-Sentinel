"""Intrusion detection: detector contract, concrete detectors and the engine."""

from app.detection.base import (
    AttackDetector,
    AttackType,
    DetectionResult,
    Severity,
    ThreatLevel,
    default_severity,
    severity_rank,
)
from app.detection.engine import AnalysisOutcome, DetectionEngine, build_default_detectors
from app.detection.fake_speed import FakeSpeedDetector
from app.detection.flood import FloodDetector
from app.detection.frequency import FrequencyAnomalyDetector
from app.detection.id_anomaly import IdAnomalyDetector

__all__ = [
    "AnalysisOutcome",
    "AttackDetector",
    "AttackType",
    "DetectionEngine",
    "DetectionResult",
    "FakeSpeedDetector",
    "FloodDetector",
    "FrequencyAnomalyDetector",
    "IdAnomalyDetector",
    "Severity",
    "ThreatLevel",
    "build_default_detectors",
    "default_severity",
    "severity_rank",
]
