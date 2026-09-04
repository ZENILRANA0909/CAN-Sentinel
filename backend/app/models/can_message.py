"""Recorded CAN traffic."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.can.message import CanMessage
from app.models.base import Base, utcnow


class CanMessageRecord(Base):
    """One CAN frame as it was observed on the bus.

    ``timestamp`` is stored as epoch seconds because every query in the product
    is a time-range or ordering query, and a float comparison is markedly
    cheaper than parsing a datetime on SQLite.
    """

    __tablename__ = "can_messages"
    __table_args__ = (
        Index("ix_can_messages_ts_id", "timestamp", "can_id"),
        Index("ix_can_messages_id_ts", "can_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    can_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    can_id_hex: Mapped[str] = mapped_column(String(12), nullable=False)
    is_extended_id: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dlc: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    channel: Mapped[str] = mapped_column(String(64), nullable=False, default="vcan0")
    direction: Mapped[str] = mapped_column(String(8), nullable=False, default="RX")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="SIMULATOR")
    message_type: Mapped[str] = mapped_column(String(8), nullable=False, default="DATA")
    flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @classmethod
    def row_from_message(cls, message: CanMessage, *, flagged: bool = False) -> dict[str, Any]:
        """Build an ``executemany``-friendly row dict (no ORM instantiation)."""
        return {
            "timestamp": message.timestamp,
            "can_id": message.arbitration_id,
            "can_id_hex": message.can_id_hex,
            "is_extended_id": message.is_extended_id,
            "dlc": message.dlc,
            "data": message.data_hex,
            "channel": message.channel,
            "direction": message.direction.value,
            "source": message.source.value,
            "message_type": message.message_type.value,
            "flagged": flagged,
            "created_at": utcnow(),
        }

    def to_wire(self) -> dict[str, Any]:
        from datetime import UTC
        from datetime import datetime as _dt

        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "iso_timestamp": _dt.fromtimestamp(self.timestamp, tz=UTC).isoformat(),
            "can_id": self.can_id,
            "can_id_hex": self.can_id_hex,
            "is_extended_id": self.is_extended_id,
            "dlc": self.dlc,
            "data": self.data,
            "channel": self.channel,
            "direction": self.direction,
            "source": self.source,
            "message_type": self.message_type,
            "flagged": self.flagged,
        }
