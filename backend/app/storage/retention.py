"""Data retention.

A monitor that runs for weeks at a few hundred frames a second will fill a disk
if nothing prunes it.  This service enforces both a row-count ceiling and a
maximum age on each table, on a configurable interval.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from app.core.exceptions import StorageError
from app.core.logging import get_logger
from app.core.runtime_config import ConfigService
from app.storage.database import Database
from app.storage.repositories import (
    CanMessageRepository,
    SecurityEventRepository,
    SystemEventRepository,
)

logger = get_logger("storage.retention")

#: How long shutdown waits for an in-flight retention pass to finish.
SHUTDOWN_TIMEOUT_SECONDS = 15.0


class RetentionService:
    """Periodically prunes stored traffic and events."""

    def __init__(
        self,
        database: Database,
        config_service: ConfigService,
        *,
        interval_seconds: float = 60.0,
    ) -> None:
        self._db = database
        self._config = config_service
        self._interval = max(1.0, interval_seconds)
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._stop_requested: asyncio.Event | None = None
        self._last_run: float | None = None
        self._last_deleted: dict[str, int] = {}
        self._total_deleted = 0
        self._errors = 0

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_requested = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="can-sentinel-retention")
        logger.info(
            "Retention service started", extra={"context": {"interval_seconds": self._interval}}
        )

    async def stop(self) -> None:
        """Stop after any in-flight pass completes.

        A retention pass runs on a worker thread via ``asyncio.to_thread``,
        which cannot be cancelled: cancelling the task would leave that thread
        using the database connection while the engine is being disposed. So
        the loop is asked to stop and then awaited, rather than cancelled.
        """
        if not self._running:
            return
        self._running = False
        if self._stop_requested is not None:
            self._stop_requested.set()
        task, self._task = self._task, None
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=SHUTDOWN_TIMEOUT_SECONDS)
            except TimeoutError:  # pragma: no cover - very slow disk
                logger.warning("Retention pass did not finish in time; cancelling")
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        logger.info("Retention service stopped")

    async def _run(self) -> None:
        assert self._stop_requested is not None
        while self._running:
            try:
                await asyncio.wait_for(
                    self._stop_requested.wait(), timeout=self._interval
                )
                return  # stop requested during the idle period
            except TimeoutError:
                pass
            except asyncio.CancelledError:  # pragma: no cover - forced shutdown
                raise
            try:
                await self.run_once()
            except asyncio.CancelledError:  # pragma: no cover - forced shutdown
                raise
            except Exception as exc:  # pragma: no cover - defensive
                self._errors += 1
                logger.error(
                    "Retention pass failed", exc_info=True, extra={"context": {"error": str(exc)}}
                )

    async def run_once(self) -> dict[str, int]:
        """Run a single retention pass on a worker thread."""
        config = self._config.current.retention
        if not config.enabled:
            return {}
        try:
            deleted = await asyncio.to_thread(self._prune, config.model_dump())
        except StorageError as exc:
            self._errors += 1
            logger.error("Retention pass failed", extra={"context": {"error": str(exc)}})
            return {}
        self._last_run = time.time()
        self._last_deleted = deleted
        self._total_deleted += sum(deleted.values())
        if any(deleted.values()):
            logger.info("Retention pass completed", extra={"context": deleted})
        return deleted

    def _prune(self, config: dict[str, Any]) -> dict[str, int]:
        max_age = float(config["max_age_days"]) * 86_400
        with self._db.session() as session:
            messages = CanMessageRepository(session).prune(
                max_rows=int(config["max_messages"]), max_age_seconds=max_age
            )
            security = SecurityEventRepository(session).prune(
                max_rows=int(config["max_security_events"]), max_age_seconds=max_age
            )
            system = SystemEventRepository(session).prune(
                max_rows=int(config["max_system_events"]), max_age_seconds=max_age
            )
        return {"can_messages": messages, "security_events": security, "system_events": system}

    def status(self) -> dict[str, Any]:
        config = self._config.current.retention
        return {
            "enabled": config.enabled,
            "running": self._running,
            "interval_seconds": self._interval,
            "last_run": self._last_run,
            "last_deleted": self._last_deleted,
            "total_deleted": self._total_deleted,
            "errors": self._errors,
            "limits": {
                "max_messages": config.max_messages,
                "max_security_events": config.max_security_events,
                "max_system_events": config.max_system_events,
                "max_age_days": config.max_age_days,
            },
        }
