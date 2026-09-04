"""Batched, non-blocking persistence.

The receive loop must never wait on a disk write.  It hands rows to this
writer, which buffers them in a bounded queue and commits them from a
background task on a worker thread.

When the queue fills - a sustained flood faster than SQLite can absorb - rows
are dropped and counted rather than allowing unbounded memory growth or
stalling the monitor.  Security events are given their own queue so that a
torrent of raw traffic can never push an attack record out: dropping evidence
would defeat the product.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from app.core.exceptions import StorageError
from app.core.logging import get_logger
from app.models.can_message import CanMessageRecord
from app.models.security_event import SecurityEventRecord
from app.models.system_event import SystemEventRecord
from app.storage.database import Database

logger = get_logger("storage.writer")

#: Security and system events are low volume, so a small dedicated queue is
#: plenty and guarantees they are never crowded out by traffic rows.
EVENT_QUEUE_SIZE = 5000
SHUTDOWN_DRAIN_SECONDS = 5.0


class PersistenceWriter:
    """Background batching writer for traffic and event rows."""

    def __init__(
        self,
        database: Database,
        *,
        queue_size: int = 20_000,
        batch_size: int = 500,
        interval_seconds: float = 0.5,
    ) -> None:
        self._db = database
        self._batch_size = max(1, batch_size)
        self._interval = max(0.01, interval_seconds)
        self._messages: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max(100, queue_size))
        self._events: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(
            maxsize=EVENT_QUEUE_SIZE
        )
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._stop_requested: asyncio.Event | None = None
        # The API flushes on demand so a query never reads stale data, while the
        # background loop flushes on its timer. Without this, both could commit
        # the same batch concurrently.
        self._flush_lock = asyncio.Lock()
        self._stats = {
            "messages_written": 0,
            "messages_dropped": 0,
            "security_events_written": 0,
            "security_events_dropped": 0,
            "system_events_written": 0,
            "batches": 0,
            "errors": 0,
        }
        self._last_error: str | None = None
        self._last_write: float | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_requested = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="can-sentinel-db-writer")
        logger.info("Persistence writer started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._stop_requested is not None:
            self._stop_requested.set()
        task, self._task = self._task, None
        if task is not None:
            # A batch commit runs on a worker thread that cannot be cancelled;
            # awaiting the loop keeps the engine alive until that thread is done.
            try:
                await asyncio.wait_for(task, timeout=SHUTDOWN_DRAIN_SECONDS)
            except TimeoutError:  # pragma: no cover - slow disk
                logger.warning("Writer loop did not stop in time; cancelling")
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        # Commit whatever is still buffered so a clean shutdown loses nothing.
        try:
            await asyncio.wait_for(self.flush(), timeout=SHUTDOWN_DRAIN_SECONDS)
        except TimeoutError:  # pragma: no cover - slow disk
            logger.warning("Timed out draining the persistence queue during shutdown")
        except StorageError as exc:  # pragma: no cover - disk failure at shutdown
            logger.error("Final flush failed", extra={"context": {"error": str(exc)}})
        logger.info("Persistence writer stopped", extra={"context": self.stats()})

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------ #
    # Submission (never blocks, never raises)                            #
    # ------------------------------------------------------------------ #
    def submit_messages(self, rows: list[dict[str, Any]]) -> int:
        """Queue traffic rows; returns how many were accepted."""
        accepted = 0
        for row in rows:
            try:
                self._messages.put_nowait(row)
            except asyncio.QueueFull:
                self._stats["messages_dropped"] += 1
            else:
                accepted += 1
        return accepted

    def submit_security_events(self, rows: list[dict[str, Any]]) -> int:
        accepted = 0
        for row in rows:
            try:
                self._events.put_nowait(("security", row))
            except asyncio.QueueFull:  # pragma: no cover - requires 5k backlog
                self._stats["security_events_dropped"] += 1
                logger.error("Security event queue full; event dropped")
            else:
                accepted += 1
        return accepted

    def submit_system_event(
        self,
        *,
        event_type: str,
        message: str,
        severity: str = "INFO",
        context: dict[str, Any] | None = None,
    ) -> bool:
        row = SystemEventRecord.build_row(
            timestamp=time.time(),
            event_type=event_type,
            message=message,
            severity=severity,
            context=context,
        )
        try:
            self._events.put_nowait(("system", row))
        except asyncio.QueueFull:  # pragma: no cover
            return False
        return True

    # ------------------------------------------------------------------ #
    # Draining                                                           #
    # ------------------------------------------------------------------ #
    async def _run(self) -> None:
        assert self._stop_requested is not None
        while self._running:
            try:
                await asyncio.wait_for(self._stop_requested.wait(), timeout=self._interval)
                return  # stop requested; the final flush happens in stop()
            except TimeoutError:
                pass
            except asyncio.CancelledError:  # pragma: no cover - forced shutdown
                raise
            try:
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                self._stats["errors"] += 1
                self._last_error = str(exc)
                logger.error(
                    "Persistence writer iteration failed",
                    exc_info=True,
                    extra={"context": {"error": str(exc)}},
                )
                await asyncio.sleep(min(self._interval * 4, 5.0))

    async def flush(self) -> dict[str, int]:
        """Commit everything currently queued. Safe to call at any time."""
        async with self._flush_lock:
            return await self._flush_once()

    async def _flush_once(self) -> dict[str, int]:
        message_rows = _drain(self._messages, self._batch_size * 4)
        event_items = _drain(self._events, self._batch_size)
        if not message_rows and not event_items:
            return {"messages": 0, "security_events": 0, "system_events": 0}

        security_rows = [row for kind, row in event_items if kind == "security"]
        system_rows = [row for kind, row in event_items if kind == "system"]

        try:
            await asyncio.to_thread(self._write, message_rows, security_rows, system_rows)
        except StorageError as exc:
            self._stats["errors"] += 1
            self._last_error = str(exc)
            logger.error("Batch write failed", extra={"context": {"error": str(exc)}})
            raise

        self._stats["messages_written"] += len(message_rows)
        self._stats["security_events_written"] += len(security_rows)
        self._stats["system_events_written"] += len(system_rows)
        self._stats["batches"] += 1
        self._last_write = time.time()
        return {
            "messages": len(message_rows),
            "security_events": len(security_rows),
            "system_events": len(system_rows),
        }

    def _write(
        self,
        message_rows: list[dict[str, Any]],
        security_rows: list[dict[str, Any]],
        system_rows: list[dict[str, Any]],
    ) -> None:
        """Single transaction covering the whole batch (runs on a worker thread)."""
        with self._db.session() as session:
            if message_rows:
                session.execute(CanMessageRecord.__table__.insert(), message_rows)
            if security_rows:
                session.execute(SecurityEventRecord.__table__.insert(), security_rows)
            if system_rows:
                session.execute(SystemEventRecord.__table__.insert(), system_rows)

    # ------------------------------------------------------------------ #
    def stats(self) -> dict[str, Any]:
        return {
            **self._stats,
            "running": self._running,
            "queued_messages": self._messages.qsize(),
            "queued_events": self._events.qsize(),
            "message_queue_capacity": self._messages.maxsize,
            "last_error": self._last_error,
            "last_write": self._last_write,
        }


def _drain(queue: asyncio.Queue[Any], limit: int) -> list[Any]:
    """Pull up to ``limit`` items without awaiting."""
    items: list[Any] = []
    while len(items) < limit:
        try:
            items.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return items
