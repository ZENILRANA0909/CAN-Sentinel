"""Query layer.

Repositories are plain synchronous functions over a SQLAlchemy ``Session``.
The API layer runs them on a worker thread; the test-suite calls them directly.
Keeping them free of async machinery makes both straightforward.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Integer, Select, delete, func, select
from sqlalchemy.orm import Session

from app.detection.base import DetectionResult
from app.models.can_message import CanMessageRecord
from app.models.security_event import EventStatus, SecurityEventRecord
from app.models.system_event import SystemEventRecord

#: Hard ceiling on any single page, so a malicious or careless ``limit`` cannot
#: pull the whole table into memory.
MAX_PAGE_SIZE = 1000


def clamp_limit(limit: int, default: int = 100) -> int:
    """Constrain a caller supplied page size to a sane range."""
    if limit <= 0:
        return default
    return min(limit, MAX_PAGE_SIZE)


@dataclass(frozen=True)
class Page:
    """A slice of rows plus the total matching count."""

    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


# --------------------------------------------------------------------------- #
# CAN messages                                                                #
# --------------------------------------------------------------------------- #
class CanMessageRepository:
    """Reads and writes over recorded CAN traffic."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def bulk_insert(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        self.session.execute(CanMessageRecord.__table__.insert(), rows)
        return len(rows)

    def _filtered(
        self,
        *,
        can_id: int | None = None,
        since: float | None = None,
        until: float | None = None,
        source: str | None = None,
        flagged_only: bool = False,
        data_contains: str | None = None,
    ) -> Select[Any]:
        stmt = select(CanMessageRecord)
        if can_id is not None:
            stmt = stmt.where(CanMessageRecord.can_id == can_id)
        if since is not None:
            stmt = stmt.where(CanMessageRecord.timestamp >= since)
        if until is not None:
            stmt = stmt.where(CanMessageRecord.timestamp <= until)
        if source:
            stmt = stmt.where(CanMessageRecord.source == source)
        if flagged_only:
            stmt = stmt.where(CanMessageRecord.flagged.is_(True))
        if data_contains:
            stmt = stmt.where(CanMessageRecord.data.contains(data_contains.upper()))
        return stmt

    def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        can_id: int | None = None,
        since: float | None = None,
        until: float | None = None,
        source: str | None = None,
        flagged_only: bool = False,
        data_contains: str | None = None,
    ) -> Page:
        limit = clamp_limit(limit)
        offset = max(offset, 0)
        base = self._filtered(
            can_id=can_id,
            since=since,
            until=until,
            source=source,
            flagged_only=flagged_only,
            data_contains=data_contains,
        )
        total = self.session.scalar(
            select(func.count()).select_from(base.subquery())
        ) or 0
        rows = self.session.scalars(
            base.order_by(CanMessageRecord.timestamp.desc(), CanMessageRecord.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return Page([row.to_wire() for row in rows], total=int(total), limit=limit, offset=offset)

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = clamp_limit(limit)
        rows = self.session.scalars(
            select(CanMessageRecord)
            .order_by(CanMessageRecord.timestamp.desc(), CanMessageRecord.id.desc())
            .limit(limit)
        ).all()
        return [row.to_wire() for row in rows]

    def count(self) -> int:
        return int(self.session.scalar(select(func.count(CanMessageRecord.id))) or 0)

    def counts_by_can_id(
        self, *, since: float | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        stmt = select(
            CanMessageRecord.can_id,
            CanMessageRecord.can_id_hex,
            func.count(CanMessageRecord.id).label("count"),
        )
        if since is not None:
            stmt = stmt.where(CanMessageRecord.timestamp >= since)
        stmt = (
            stmt.group_by(CanMessageRecord.can_id, CanMessageRecord.can_id_hex)
            .order_by(func.count(CanMessageRecord.id).desc())
            .limit(clamp_limit(limit, default=20))
        )
        return [
            {"can_id": row.can_id, "can_id_hex": row.can_id_hex, "count": int(row.count)}
            for row in self.session.execute(stmt)
        ]

    def time_bounds(self) -> tuple[float | None, float | None]:
        row = self.session.execute(
            select(func.min(CanMessageRecord.timestamp), func.max(CanMessageRecord.timestamp))
        ).one()
        return row[0], row[1]

    def prune(self, *, max_rows: int, max_age_seconds: float | None = None) -> int:
        """Enforce retention. Returns the number of rows deleted."""
        deleted = 0
        if max_age_seconds is not None:
            cutoff = time.time() - max_age_seconds
            result = self.session.execute(
                delete(CanMessageRecord).where(CanMessageRecord.timestamp < cutoff)
            )
            deleted += int(result.rowcount or 0)
        total = self.count()
        if total > max_rows:
            excess = total - max_rows
            # Delete the oldest rows by primary key, which is insertion order.
            ids = self.session.scalars(
                select(CanMessageRecord.id).order_by(CanMessageRecord.id.asc()).limit(excess)
            ).all()
            if ids:
                result = self.session.execute(
                    delete(CanMessageRecord).where(CanMessageRecord.id.in_(ids))
                )
                deleted += int(result.rowcount or 0)
        return deleted


# --------------------------------------------------------------------------- #
# Security events                                                             #
# --------------------------------------------------------------------------- #
class SecurityEventRepository:
    """Reads and writes over detected security events."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def bulk_insert(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        self.session.execute(SecurityEventRecord.__table__.insert(), rows)
        return len(rows)

    def insert_result(self, result: DetectionResult, *, channel: str = "vcan0") -> int:
        record = SecurityEventRecord(**SecurityEventRecord.row_from_result(result, channel=channel))
        self.session.add(record)
        self.session.flush()
        return record.id

    def _filtered(
        self,
        *,
        attack_type: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        detector: str | None = None,
        can_id: int | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> Select[Any]:
        stmt = select(SecurityEventRecord)
        if attack_type:
            stmt = stmt.where(SecurityEventRecord.attack_type == attack_type)
        if severity:
            stmt = stmt.where(SecurityEventRecord.severity == severity)
        if status:
            stmt = stmt.where(SecurityEventRecord.status == status)
        if detector:
            stmt = stmt.where(SecurityEventRecord.detector == detector)
        if can_id is not None:
            stmt = stmt.where(SecurityEventRecord.can_id == can_id)
        if since is not None:
            stmt = stmt.where(SecurityEventRecord.timestamp >= since)
        if until is not None:
            stmt = stmt.where(SecurityEventRecord.timestamp <= until)
        return stmt

    def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        attack_type: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        detector: str | None = None,
        can_id: int | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> Page:
        limit = clamp_limit(limit)
        offset = max(offset, 0)
        base = self._filtered(
            attack_type=attack_type,
            severity=severity,
            status=status,
            detector=detector,
            can_id=can_id,
            since=since,
            until=until,
        )
        total = self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self.session.scalars(
            base.order_by(SecurityEventRecord.timestamp.desc(), SecurityEventRecord.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return Page([row.to_wire() for row in rows], total=int(total), limit=limit, offset=offset)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = clamp_limit(limit)
        rows = self.session.scalars(
            select(SecurityEventRecord)
            .order_by(SecurityEventRecord.timestamp.desc(), SecurityEventRecord.id.desc())
            .limit(limit)
        ).all()
        return [row.to_wire() for row in rows]

    def get(self, event_id: int) -> dict[str, Any] | None:
        row = self.session.get(SecurityEventRecord, event_id)
        return row.to_wire() if row else None

    def set_status(self, event_id: int, status: EventStatus) -> dict[str, Any] | None:
        row = self.session.get(SecurityEventRecord, event_id)
        if row is None:
            return None
        row.status = status.value
        self.session.flush()
        return row.to_wire()

    def count(self, *, since: float | None = None) -> int:
        stmt = select(func.count(SecurityEventRecord.id))
        if since is not None:
            stmt = stmt.where(SecurityEventRecord.timestamp >= since)
        return int(self.session.scalar(stmt) or 0)

    def counts_by(self, column: str, *, since: float | None = None) -> dict[str, int]:
        target = {
            "attack_type": SecurityEventRecord.attack_type,
            "severity": SecurityEventRecord.severity,
            "status": SecurityEventRecord.status,
            "detector": SecurityEventRecord.detector,
            "threat_level": SecurityEventRecord.threat_level,
        }[column]
        stmt = select(target, func.count(SecurityEventRecord.id))
        if since is not None:
            stmt = stmt.where(SecurityEventRecord.timestamp >= since)
        stmt = stmt.group_by(target)
        return {str(key): int(value) for key, value in self.session.execute(stmt)}

    def top_can_ids(self, *, limit: int = 10, since: float | None = None) -> list[dict[str, Any]]:
        stmt = select(
            SecurityEventRecord.can_id,
            SecurityEventRecord.can_id_hex,
            func.count(SecurityEventRecord.id).label("count"),
        ).where(SecurityEventRecord.can_id.is_not(None))
        if since is not None:
            stmt = stmt.where(SecurityEventRecord.timestamp >= since)
        stmt = (
            stmt.group_by(SecurityEventRecord.can_id, SecurityEventRecord.can_id_hex)
            .order_by(func.count(SecurityEventRecord.id).desc())
            .limit(clamp_limit(limit, default=10))
        )
        return [
            {"can_id": row.can_id, "can_id_hex": row.can_id_hex, "count": int(row.count)}
            for row in self.session.execute(stmt)
        ]

    def timeline(
        self, *, bucket_seconds: int = 60, since: float | None = None, buckets: int = 60
    ) -> list[dict[str, Any]]:
        """Attack counts grouped into fixed time buckets, oldest first."""
        bucket_seconds = max(1, bucket_seconds)
        if since is None:
            since = time.time() - bucket_seconds * buckets
        bucket_expr = func.cast(
            SecurityEventRecord.timestamp / bucket_seconds, Integer
        ).label("bucket")
        stmt = (
            select(bucket_expr, SecurityEventRecord.severity, func.count(SecurityEventRecord.id))
            .where(SecurityEventRecord.timestamp >= since)
            .group_by("bucket", SecurityEventRecord.severity)
            .order_by("bucket")
        )
        grouped: dict[int, dict[str, Any]] = {}
        for bucket, severity, count in self.session.execute(stmt):
            entry = grouped.setdefault(
                int(bucket), {"bucket_start": int(bucket) * bucket_seconds, "total": 0}
            )
            entry[str(severity)] = int(count)
            entry["total"] += int(count)
        return [grouped[key] for key in sorted(grouped)]

    def prune(self, *, max_rows: int, max_age_seconds: float | None = None) -> int:
        deleted = 0
        if max_age_seconds is not None:
            cutoff = time.time() - max_age_seconds
            result = self.session.execute(
                delete(SecurityEventRecord).where(SecurityEventRecord.timestamp < cutoff)
            )
            deleted += int(result.rowcount or 0)
        total = self.count()
        if total > max_rows:
            ids = self.session.scalars(
                select(SecurityEventRecord.id)
                .order_by(SecurityEventRecord.id.asc())
                .limit(total - max_rows)
            ).all()
            if ids:
                result = self.session.execute(
                    delete(SecurityEventRecord).where(SecurityEventRecord.id.in_(ids))
                )
                deleted += int(result.rowcount or 0)
        return deleted


# --------------------------------------------------------------------------- #
# System events                                                               #
# --------------------------------------------------------------------------- #
class SystemEventRepository:
    """Audit-trail access."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def bulk_insert(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        self.session.execute(SystemEventRecord.__table__.insert(), rows)
        return len(rows)

    def record(
        self,
        *,
        event_type: str,
        message: str,
        severity: str = "INFO",
        context: dict[str, Any] | None = None,
        timestamp: float | None = None,
    ) -> int:
        row = SystemEventRecord(
            **SystemEventRecord.build_row(
                timestamp=timestamp if timestamp is not None else time.time(),
                event_type=event_type,
                message=message,
                severity=severity,
                context=context,
            )
        )
        self.session.add(row)
        self.session.flush()
        return row.id

    def recent(self, limit: int = 50, *, event_type: str | None = None) -> list[dict[str, Any]]:
        stmt = select(SystemEventRecord)
        if event_type:
            stmt = stmt.where(SystemEventRecord.event_type == event_type)
        rows = self.session.scalars(
            stmt.order_by(SystemEventRecord.timestamp.desc(), SystemEventRecord.id.desc()).limit(
                clamp_limit(limit, default=50)
            )
        ).all()
        return [row.to_wire() for row in rows]

    def count(self) -> int:
        return int(self.session.scalar(select(func.count(SystemEventRecord.id))) or 0)

    def prune(self, *, max_rows: int, max_age_seconds: float | None = None) -> int:
        deleted = 0
        if max_age_seconds is not None:
            cutoff = time.time() - max_age_seconds
            result = self.session.execute(
                delete(SystemEventRecord).where(SystemEventRecord.timestamp < cutoff)
            )
            deleted += int(result.rowcount or 0)
        total = self.count()
        if total > max_rows:
            ids = self.session.scalars(
                select(SystemEventRecord.id)
                .order_by(SystemEventRecord.id.asc())
                .limit(total - max_rows)
            ).all()
            if ids:
                result = self.session.execute(
                    delete(SystemEventRecord).where(SystemEventRecord.id.in_(ids))
                )
                deleted += int(result.rowcount or 0)
        return deleted
