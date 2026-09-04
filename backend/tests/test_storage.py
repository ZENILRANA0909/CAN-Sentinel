"""Database, repositories, batching writer and retention."""

from __future__ import annotations

import time

import pytest

from app.core.exceptions import StorageError
from app.core.runtime_config import ConfigService
from app.detection.base import AttackType, DetectionResult, Severity, ThreatLevel
from app.models.can_message import CanMessageRecord
from app.models.security_event import EventStatus, SecurityEventRecord
from app.storage.database import Database
from app.storage.repositories import (
    MAX_PAGE_SIZE,
    CanMessageRepository,
    SecurityEventRepository,
    SystemEventRepository,
    clamp_limit,
)
from app.storage.retention import RetentionService
from app.storage.writer import PersistenceWriter
from tests.conftest import make_message


def seed_messages(database: Database, count: int, *, start: float = 1000.0, can_id: int = 0x100) -> None:
    rows = [
        CanMessageRecord.row_from_message(
            make_message(can_id=can_id, timestamp=start + index), flagged=index % 5 == 0
        )
        for index in range(count)
    ]
    with database.session() as session:
        CanMessageRepository(session).bulk_insert(rows)


def make_result(**overrides) -> DetectionResult:
    payload = {
        "detector": "fake_speed",
        "detected": True,
        "threat_level": ThreatLevel.ATTACK,
        "attack_type": AttackType.FAKE_SPEED,
        "severity": Severity.HIGH,
        "confidence": 0.9,
        "can_id": 0x300,
        "timestamp": time.time(),
        "description": "Forged vehicle speed",
        "evidence": {"observed_speed_kmh": 255.0},
    }
    payload.update(overrides)
    return DetectionResult(**payload)


class TestDatabase:
    def test_schema_is_created(self, database: Database) -> None:
        assert database.is_connected
        health = database.healthcheck()
        assert health["healthy"] is True

    def test_unconnected_database_reports_unhealthy(self) -> None:
        db = Database("sqlite:///:memory:")
        assert db.healthcheck()["healthy"] is False

    def test_session_requires_a_connection(self) -> None:
        db = Database("sqlite:///:memory:")
        with pytest.raises(StorageError, match="not connected"), db.session():
            pass

    def test_session_rolls_back_on_error(self, database: Database) -> None:
        with pytest.raises(ValueError), database.session() as session:
            CanMessageRepository(session).bulk_insert(
                [CanMessageRecord.row_from_message(make_message())]
            )
            raise ValueError("boom")
        with database.session() as session:
            assert CanMessageRepository(session).count() == 0

    def test_credentials_are_not_leaked_in_status(self) -> None:
        db = Database("postgresql://user:secret@host/db")
        assert "secret" not in db._safe_url()


class TestCanMessageRepository:
    def test_bulk_insert_and_count(self, database: Database) -> None:
        seed_messages(database, 10)
        with database.session() as session:
            assert CanMessageRepository(session).count() == 10

    def test_recent_returns_newest_first(self, database: Database) -> None:
        seed_messages(database, 10)
        with database.session() as session:
            rows = CanMessageRepository(session).recent(3)
        assert len(rows) == 3
        assert rows[0]["timestamp"] > rows[1]["timestamp"]

    def test_pagination_reports_the_true_total(self, database: Database) -> None:
        seed_messages(database, 50)
        with database.session() as session:
            page = CanMessageRepository(session).list(limit=10, offset=0)
        assert len(page.items) == 10
        assert page.total == 50
        assert page.has_more is True

    def test_last_page_reports_no_more(self, database: Database) -> None:
        seed_messages(database, 15)
        with database.session() as session:
            page = CanMessageRepository(session).list(limit=10, offset=10)
        assert len(page.items) == 5
        assert page.has_more is False

    def test_filters(self, database: Database) -> None:
        seed_messages(database, 10, can_id=0x100)
        seed_messages(database, 5, can_id=0x200, start=2000.0)
        with database.session() as session:
            repo = CanMessageRepository(session)
            assert repo.list(can_id=0x200).total == 5
            assert repo.list(since=2000.0).total == 5
            assert repo.list(flagged_only=True).total == 3  # index 0, 5 of ten, 0 of five
            assert repo.list(source="SIMULATOR").total == 15
            assert repo.list(source="HARDWARE").total == 0

    def test_counts_by_can_id(self, database: Database) -> None:
        seed_messages(database, 10, can_id=0x100)
        seed_messages(database, 4, can_id=0x200, start=2000.0)
        with database.session() as session:
            counts = CanMessageRepository(session).counts_by_can_id()
        assert counts[0] == {"can_id": 0x100, "can_id_hex": "0x100", "count": 10}

    def test_limit_is_clamped(self) -> None:
        assert clamp_limit(10_000) == MAX_PAGE_SIZE
        assert clamp_limit(0) == 100
        assert clamp_limit(-5, default=25) == 25

    def test_prune_enforces_the_row_cap(self, database: Database) -> None:
        seed_messages(database, 100)
        with database.session() as session:
            repo = CanMessageRepository(session)
            deleted = repo.prune(max_rows=30)
            assert deleted == 70
            assert repo.count() == 30

    def test_prune_removes_rows_older_than_the_age_limit(self, database: Database) -> None:
        now = time.time()
        rows = [
            CanMessageRecord.row_from_message(make_message(timestamp=now - offset))
            for offset in (10, 100, 100_000)
        ]
        with database.session() as session:
            CanMessageRepository(session).bulk_insert(rows)
        with database.session() as session:
            repo = CanMessageRepository(session)
            repo.prune(max_rows=1_000_000, max_age_seconds=3_600)
            assert repo.count() == 2


class TestSecurityEventRepository:
    def test_insert_and_read_back_evidence(self, database: Database) -> None:
        with database.session() as session:
            event_id = SecurityEventRepository(session).insert_result(make_result())
        with database.session() as session:
            row = SecurityEventRepository(session).get(event_id)
        assert row is not None
        assert row["attack_type"] == "FAKE_SPEED"
        assert row["evidence"]["observed_speed_kmh"] == 255.0
        assert row["status"] == "NEW"

    def test_status_transitions(self, database: Database) -> None:
        with database.session() as session:
            event_id = SecurityEventRepository(session).insert_result(make_result())
        with database.session() as session:
            updated = SecurityEventRepository(session).set_status(event_id, EventStatus.RESOLVED)
        assert updated is not None
        assert updated["status"] == "RESOLVED"

    def test_status_update_on_missing_event_returns_none(self, database: Database) -> None:
        with database.session() as session:
            assert SecurityEventRepository(session).set_status(999, EventStatus.RESOLVED) is None

    def test_counts_by_dimension(self, database: Database) -> None:
        with database.session() as session:
            repo = SecurityEventRepository(session)
            repo.insert_result(make_result())
            repo.insert_result(make_result(attack_type=AttackType.CAN_FLOOD, severity=Severity.CRITICAL))
        with database.session() as session:
            repo = SecurityEventRepository(session)
            assert repo.counts_by("attack_type") == {"FAKE_SPEED": 1, "CAN_FLOOD": 1}
            assert repo.counts_by("severity") == {"HIGH": 1, "CRITICAL": 1}

    def test_top_can_ids(self, database: Database) -> None:
        with database.session() as session:
            repo = SecurityEventRepository(session)
            for _ in range(3):
                repo.insert_result(make_result(can_id=0x300))
            repo.insert_result(make_result(can_id=0x100))
        with database.session() as session:
            top = SecurityEventRepository(session).top_can_ids()
        assert top[0]["can_id"] == 0x300
        assert top[0]["count"] == 3

    def test_timeline_buckets_by_severity(self, database: Database) -> None:
        now = time.time()
        with database.session() as session:
            repo = SecurityEventRepository(session)
            repo.insert_result(make_result(timestamp=now))
            repo.insert_result(make_result(timestamp=now, severity=Severity.CRITICAL))
        with database.session() as session:
            timeline = SecurityEventRepository(session).timeline(
                bucket_seconds=60, since=now - 60
            )
        assert len(timeline) == 1
        assert timeline[0]["total"] == 2
        assert timeline[0]["HIGH"] == 1
        assert timeline[0]["CRITICAL"] == 1

    def test_evidence_survives_a_corrupt_payload(self, database: Database) -> None:
        with database.session() as session:
            session.add(
                SecurityEventRecord(
                    **{**SecurityEventRecord.row_from_result(make_result()), "evidence_json": "not json"}
                )
            )
        with database.session() as session:
            row = SecurityEventRepository(session).recent(1)[0]
        assert row["evidence"] == {}


class TestSystemEventRepository:
    def test_record_and_read(self, database: Database) -> None:
        with database.session() as session:
            SystemEventRepository(session).record(
                event_type="MONITOR_STARTED", message="up", context={"channel": "vcan0"}
            )
        with database.session() as session:
            rows = SystemEventRepository(session).recent(10)
        assert rows[0]["event_type"] == "MONITOR_STARTED"
        assert rows[0]["context"]["channel"] == "vcan0"

    def test_filter_by_type(self, database: Database) -> None:
        with database.session() as session:
            repo = SystemEventRepository(session)
            repo.record(event_type="A", message="a")
            repo.record(event_type="B", message="b")
        with database.session() as session:
            rows = SystemEventRepository(session).recent(10, event_type="B")
        assert len(rows) == 1


class TestPersistenceWriter:
    async def test_writes_batches_in_the_background(self, database: Database) -> None:
        writer = PersistenceWriter(database, batch_size=100, interval_seconds=0.02)
        await writer.start()
        try:
            writer.submit_messages(
                [CanMessageRecord.row_from_message(make_message()) for _ in range(250)]
            )
            written = await writer.flush()
            assert written["messages"] == 250
        finally:
            await writer.stop()
        with database.session() as session:
            assert CanMessageRepository(session).count() == 250

    async def test_drops_and_counts_when_the_queue_is_full(self, database: Database) -> None:
        writer = PersistenceWriter(database, queue_size=100)
        rows = [CanMessageRecord.row_from_message(make_message()) for _ in range(150)]
        accepted = writer.submit_messages(rows)
        assert accepted == 100
        assert writer.stats()["messages_dropped"] == 50

    async def test_security_events_have_a_separate_queue(self, database: Database) -> None:
        """A traffic flood must never push an attack record out of the queue."""
        writer = PersistenceWriter(database, queue_size=100)
        writer.submit_messages([CanMessageRecord.row_from_message(make_message())] * 500)
        assert writer.stats()["messages_dropped"] > 0

        accepted = writer.submit_security_events(
            [SecurityEventRecord.row_from_result(make_result())]
        )
        assert accepted == 1
        assert writer.stats()["security_events_dropped"] == 0

    async def test_flush_commits_all_three_tables_together(self, database: Database) -> None:
        writer = PersistenceWriter(database)
        writer.submit_messages([CanMessageRecord.row_from_message(make_message())])
        writer.submit_security_events([SecurityEventRecord.row_from_result(make_result())])
        writer.submit_system_event(event_type="TEST", message="hello")
        result = await writer.flush()
        assert result == {"messages": 1, "security_events": 1, "system_events": 1}

    async def test_flush_on_an_empty_queue_is_a_no_op(self, database: Database) -> None:
        writer = PersistenceWriter(database)
        assert await writer.flush() == {"messages": 0, "security_events": 0, "system_events": 0}

    async def test_stop_drains_remaining_rows(self, database: Database) -> None:
        writer = PersistenceWriter(database, interval_seconds=10.0)
        await writer.start()
        writer.submit_messages([CanMessageRecord.row_from_message(make_message())])
        await writer.stop()
        with database.session() as session:
            assert CanMessageRepository(session).count() == 1


class TestRetention:
    async def test_prunes_rows_older_than_the_age_limit(
        self, database: Database, config_service: ConfigService
    ) -> None:
        now = time.time()
        rows = [
            CanMessageRecord.row_from_message(make_message(timestamp=now - 60)),
            CanMessageRecord.row_from_message(make_message(timestamp=now - 3_600)),
            # Thirty days old: outside the default seven-day retention window.
            CanMessageRecord.row_from_message(make_message(timestamp=now - 30 * 86_400)),
        ]
        with database.session() as session:
            CanMessageRepository(session).bulk_insert(rows)

        config_service.update({"retention": {"enabled": True, "max_age_days": 7}})
        deleted = await RetentionService(database, config_service).run_once()

        assert deleted["can_messages"] == 1
        with database.session() as session:
            assert CanMessageRepository(session).count() == 2

    async def test_enforces_the_row_cap(
        self, database: Database, config_service: ConfigService
    ) -> None:
        now = time.time()
        # All recent, so only the row cap can remove anything.
        seed_messages(database, 1_200, start=now - 1_200)
        config_service.update({"retention": {"enabled": True, "max_messages": 1_000}})

        deleted = await RetentionService(database, config_service).run_once()

        assert deleted["can_messages"] == 200
        with database.session() as session:
            repo = CanMessageRepository(session)
            assert repo.count() == 1_000
            # The oldest rows are the ones that went.
            oldest, newest = repo.time_bounds()
            assert oldest is not None and newest is not None
            assert oldest > now - 1_200

    async def test_disabled_retention_does_nothing(
        self, database: Database, config_service: ConfigService
    ) -> None:
        seed_messages(database, 20)
        config_service.update({"retention": {"enabled": False}})
        service = RetentionService(database, config_service)
        assert await service.run_once() == {}
        with database.session() as session:
            assert CanMessageRepository(session).count() == 20

    async def test_start_and_stop_are_idempotent(
        self, database: Database, config_service: ConfigService
    ) -> None:
        service = RetentionService(database, config_service, interval_seconds=1.0)
        await service.start()
        await service.start()
        assert service.status()["running"] is True
        await service.stop()
        await service.stop()
        assert service.status()["running"] is False
