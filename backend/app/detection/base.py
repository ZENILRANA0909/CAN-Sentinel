"""Detector contract and shared vocabulary.

Every detector answers the same question about every frame and answers it with
an explicit classification.  There is no "return ``None`` and hope the caller
guesses" - a detector always produces a :class:`DetectionResult` whose
``threat_level`` is one of NORMAL / SUSPICIOUS / ATTACK.
"""

from __future__ import annotations

import abc
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.can.message import CanMessage
from app.core.runtime_config import ConfigService, DetectionConfig


class ThreatLevel(str, Enum):
    """Explicit classification produced for every inspected frame."""

    NORMAL = "NORMAL"
    SUSPICIOUS = "SUSPICIOUS"
    ATTACK = "ATTACK"


class Severity(str, Enum):
    """Operational severity attached to a security event."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AttackType(str, Enum):
    """Catalogue of conditions CAN-Sentinel can identify."""

    NONE = "NONE"
    FAKE_SPEED = "FAKE_SPEED"
    CAN_FLOOD = "CAN_FLOOD"
    ID_ANOMALY = "ID_ANOMALY"
    FREQUENCY_ANOMALY = "FREQUENCY_ANOMALY"


SEVERITY_ORDER: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}

THREAT_ORDER: dict[ThreatLevel, int] = {
    ThreatLevel.NORMAL: 0,
    ThreatLevel.SUSPICIOUS: 1,
    ThreatLevel.ATTACK: 2,
}


def severity_rank(severity: Severity) -> int:
    """Numeric rank used to compare and aggregate severities."""
    return SEVERITY_ORDER[severity]


def default_severity(threat_level: ThreatLevel, *, escalated: bool = False) -> Severity:
    """Project a threat level onto the default severity ladder.

    ==================  ==========================================
    Threat level        Severity
    ==================  ==========================================
    NORMAL              INFO
    SUSPICIOUS          LOW when mild, MEDIUM by default
    ATTACK              HIGH, escalated to CRITICAL by a detector
                        when the magnitude is extreme
    ==================  ==========================================
    """
    if threat_level is ThreatLevel.NORMAL:
        return Severity.INFO
    if threat_level is ThreatLevel.SUSPICIOUS:
        return Severity.MEDIUM if escalated else Severity.LOW
    return Severity.CRITICAL if escalated else Severity.HIGH


class DetectionResult(BaseModel):
    """The verdict of one detector about one frame."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    detector: str
    detected: bool
    threat_level: ThreatLevel
    attack_type: AttackType
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    can_id: int | None = None
    timestamp: float
    description: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def can_id_hex(self) -> str | None:
        return None if self.can_id is None else f"0x{self.can_id:03X}"

    @property
    def severity_rank(self) -> int:
        return severity_rank(self.severity)

    @classmethod
    def normal(
        cls,
        *,
        detector: str,
        timestamp: float,
        can_id: int | None = None,
        description: str = "Traffic within configured limits",
        evidence: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DetectionResult:
        """Construct the explicit "nothing wrong here" verdict."""
        return cls(
            detector=detector,
            detected=False,
            threat_level=ThreatLevel.NORMAL,
            attack_type=AttackType.NONE,
            severity=Severity.INFO,
            confidence=0.0,
            can_id=can_id,
            timestamp=timestamp,
            description=description,
            evidence=evidence or {},
            metadata=metadata or {},
        )

    def to_wire(self) -> dict[str, Any]:
        """JSON-safe representation for the API and the WebSocket stream."""
        return {
            "detector": self.detector,
            "detected": self.detected,
            "threat_level": self.threat_level.value,
            "attack_type": self.attack_type.value,
            "severity": self.severity.value,
            "confidence": round(self.confidence, 4),
            "can_id": self.can_id,
            "can_id_hex": self.can_id_hex,
            "timestamp": self.timestamp,
            "description": self.description,
            "evidence": self.evidence,
            "metadata": self.metadata,
        }


class AttackDetector(abc.ABC):
    """Base class for every detector.

    Detectors are stateful (they observe traffic over time) but must keep that
    state bounded: a detector that grows without limit would be a denial of
    service against the monitor it is supposed to protect.
    """

    #: Stable machine name, used in evidence and in the API.
    name: str = "detector"
    #: The condition this detector reports.
    attack_type: AttackType = AttackType.NONE
    #: Human readable summary shown in the UI.
    description: str = ""

    def __init__(self, config_service: ConfigService) -> None:
        self._config_service = config_service
        self._inspections = 0
        self._detections = 0

    @property
    def config(self) -> DetectionConfig:
        """Always read thresholds through this property so live edits apply."""
        return self._config_service.detection

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    # ------------------------------------------------------------------ #
    # Detection                                                          #
    # ------------------------------------------------------------------ #
    def inspect(self, message: CanMessage) -> DetectionResult:
        """Classify a frame, updating detector statistics."""
        self._inspections += 1
        result = self._inspect(message)
        if result.detected:
            self._detections += 1
        return result

    @abc.abstractmethod
    def _inspect(self, message: CanMessage) -> DetectionResult:
        """Detector specific classification. Must always return a result."""

    @abc.abstractmethod
    def reset(self) -> None:
        """Discard all accumulated state."""

    def throttle_key(self, result: DetectionResult) -> str:
        """Identity of the *condition* a verdict describes.

        The engine emits at most one security event per key per cooldown, so
        the key decides what counts as "the same ongoing attack". The default
        scopes a condition to one identifier; a detector whose condition is
        bus-wide should override this.
        """
        return f"{self.name}:{result.can_id}"

    # ------------------------------------------------------------------ #
    # Introspection                                                      #
    # ------------------------------------------------------------------ #
    def snapshot(self) -> dict[str, Any]:
        """Detector state exposed through ``/api/status`` and the System page."""
        return {
            "name": self.name,
            "attack_type": self.attack_type.value,
            "description": self.description,
            "enabled": self.enabled,
            "inspections": self._inspections,
            "detections": self._detections,
            "state": self._state_snapshot(),
        }

    def _state_snapshot(self) -> dict[str, Any]:
        """Detector specific state for the snapshot. Override where useful."""
        return {}

    def _normal(
        self,
        message: CanMessage,
        *,
        description: str = "Traffic within configured limits",
        evidence: dict[str, Any] | None = None,
    ) -> DetectionResult:
        return DetectionResult.normal(
            detector=self.name,
            timestamp=message.timestamp,
            can_id=message.arbitration_id,
            description=description,
            evidence=evidence,
        )
