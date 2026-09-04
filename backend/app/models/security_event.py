"""Persisted security events produced by the detection engine."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.detection.base import DetectionResult
from app.models.base import Base, utcnow


class EventStatus(str, Enum):
    """Triage state of a security event."""

    NEW = "NEW"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class SecurityEventRecord(Base):
    """A detection that crossed the reporting threshold."""

    __tablename__ = "security_events"
    __table_args__ = (
        Index("ix_security_events_ts_sev", "timestamp", "severity"),
        Index("ix_security_events_type_ts", "attack_type", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    attack_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    threat_level: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    detector: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    can_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    can_id_hex: Mapped[str | None] = mapped_column(String(12), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EventStatus.NEW.value, index=True
    )
    channel: Mapped[str] = mapped_column(String(64), nullable=False, default="vcan0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # ------------------------------------------------------------------ #
    @property
    def evidence(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.evidence_json)
        except (TypeError, ValueError):  # pragma: no cover - corrupt row
            return {}
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def row_from_result(
        cls, result: DetectionResult, *, channel: str = "vcan0"
    ) -> dict[str, Any]:
        """Build an ``executemany``-friendly row dict from a detection verdict."""
        return {
            "timestamp": result.timestamp,
            "attack_type": result.attack_type.value,
            "threat_level": result.threat_level.value,
            "severity": result.severity.value,
            "detector": result.detector,
            "can_id": result.can_id,
            "can_id_hex": result.can_id_hex,
            "confidence": float(result.confidence),
            "description": result.description,
            "evidence_json": json.dumps(result.evidence, default=str),
            "status": EventStatus.NEW.value,
            "channel": channel,
            "created_at": utcnow(),
        }

    def to_wire(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "iso_timestamp": datetime.fromtimestamp(self.timestamp, tz=UTC).isoformat(),
            "attack_type": self.attack_type,
            "threat_level": self.threat_level,
            "severity": self.severity,
            "detector": self.detector,
            "can_id": self.can_id,
            "can_id_hex": self.can_id_hex,
            "confidence": round(self.confidence, 4),
            "description": self.description,
            "evidence": self.evidence,
            "status": self.status,
            "channel": self.channel,
        }
