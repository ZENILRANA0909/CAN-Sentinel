"""Audit trail of system-level lifecycle events."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class SystemEventRecord(Base):
    """Startup, shutdown, monitor and simulator transitions, and errors.

    This is what lets a reviewer answer "was the monitor actually running when
    that attack was recorded?" after the fact.
    """

    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="INFO", index=True)
    context_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def context(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.context_json)
        except (TypeError, ValueError):  # pragma: no cover - corrupt row
            return {}
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def build_row(
        cls,
        *,
        timestamp: float,
        event_type: str,
        message: str,
        severity: str = "INFO",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "timestamp": timestamp,
            "event_type": event_type,
            "message": message,
            "severity": severity,
            "context_json": json.dumps(context or {}, default=str),
            "created_at": utcnow(),
        }

    def to_wire(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "iso_timestamp": datetime.fromtimestamp(self.timestamp, tz=UTC).isoformat(),
            "event_type": self.event_type,
            "message": self.message,
            "severity": self.severity,
            "context": self.context,
        }
