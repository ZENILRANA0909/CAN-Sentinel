"""Monitoring service: owns the CAN interface and the receive loop."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Any

from app.can.interface import BaseCanInterface
from app.core.exceptions import CanInterfaceError, MonitorError
from app.core.logging import get_logger
from app.services.broadcaster import Broadcaster, EventType
from app.services.pipeline import MessagePipeline
from app.storage.writer import PersistenceWriter

logger = get_logger("services.monitor")

#: Frames pulled from the interface per pipeline invocation.
DEFAULT_BATCH_SIZE = 256
#: How long the loop waits for the first frame of a batch.
DEFAULT_POLL_TIMEOUT = 0.2
#: Back-off after an unexpected loop error, so a persistent fault cannot spin.
ERROR_BACKOFF_SECONDS = 0.5


class MonitorService:
    """Drains the CAN interface into the message pipeline."""

    def __init__(
        self,
        *,
        interface_factory: Callable[[], BaseCanInterface],
        pipeline: MessagePipeline,
        broadcaster: Broadcaster,
        writer: PersistenceWriter,
        batch_size: int = DEFAULT_BATCH_SIZE,
        poll_timeout: float = DEFAULT_POLL_TIMEOUT,
    ) -> None:
        self._interface_factory = interface_factory
        self._pipeline = pipeline
        self._broadcaster = broadcaster
        self._writer = writer
        self._batch_size = max(1, batch_size)
        self._poll_timeout = max(0.01, poll_timeout)

        self._interface: BaseCanInterface | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._started_at: float | None = None
        self._stopped_at: float | None = None
        self._batches = 0
        self._errors = 0
        self._last_error: str | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #
    async def start(self) -> dict[str, Any]:
        """Open the CAN interface and begin receiving. Raises if already running."""
        if self._running:
            raise MonitorError("monitor is already running")

        # Rebuilt on every start so a configuration change to the channel,
        # bitrate or backend is picked up without restarting the process.
        interface = self._interface_factory()
        try:
            await interface.open()
        except CanInterfaceError as exc:
            self._errors += 1
            self._last_error = exc.message
            self._writer.submit_system_event(
                event_type="MONITOR_START_FAILED",
                message=exc.message,
                severity="HIGH",
                context=exc.details,
            )
            logger.error("Monitor could not open the CAN interface", extra={"context": exc.details})
            raise

        self._interface = interface
        self._running = True
        self._started_at = time.time()
        self._stopped_at = None
        self._task = asyncio.create_task(self._run(), name="can-sentinel-monitor")

        payload = self.status()
        self._writer.submit_system_event(
            event_type="MONITOR_STARTED",
            message=f"Monitoring {interface.backend} interface on {interface.channel}",
            context={"backend": interface.backend, "channel": interface.channel},
        )
        self._broadcaster.publish(EventType.MONITOR_STATUS, payload)
        logger.info(
            "Monitor started",
            extra={"context": {"backend": interface.backend, "channel": interface.channel}},
        )
        return payload

    async def stop(self) -> dict[str, Any]:
        """Stop receiving and close the interface. Idempotent."""
        if not self._running:
            return self.status()
        self._running = False
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        interface, self._interface = self._interface, None
        if interface is not None:
            try:
                await interface.close()
            except Exception as exc:  # pragma: no cover - driver dependent
                logger.warning(
                    "Error while closing the CAN interface",
                    extra={"context": {"error": str(exc)}},
                )
        self._stopped_at = time.time()
        payload = self.status()
        self._writer.submit_system_event(event_type="MONITOR_STOPPED", message="Monitoring stopped")
        self._broadcaster.publish(EventType.MONITOR_STATUS, payload)
        logger.info("Monitor stopped", extra={"context": {"batches": self._batches}})
        return payload

    # ------------------------------------------------------------------ #
    # Receive loop                                                       #
    # ------------------------------------------------------------------ #
    async def _run(self) -> None:
        interface = self._interface
        if interface is None:  # pragma: no cover - defensive
            return
        while self._running:
            try:
                batch = await interface.receive_batch(self._batch_size, timeout=self._poll_timeout)
                if not batch:
                    continue
                await self._pipeline.process_batch(batch)
                self._batches += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._errors += 1
                self._last_error = str(exc)
                logger.error(
                    "Monitor loop error", exc_info=True, extra={"context": {"error": str(exc)}}
                )
                self._writer.submit_system_event(
                    event_type="MONITOR_ERROR",
                    message=str(exc),
                    severity="HIGH",
                )
                await asyncio.sleep(ERROR_BACKOFF_SECONDS)

    # ------------------------------------------------------------------ #
    # Introspection                                                      #
    # ------------------------------------------------------------------ #
    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def interface(self) -> BaseCanInterface | None:
        return self._interface

    @property
    def uptime_seconds(self) -> float:
        if not self._running or self._started_at is None:
            return 0.0
        return time.time() - self._started_at

    def status(self) -> dict[str, Any]:
        interface = self._interface
        return {
            "running": self._running,
            "started_at": self._started_at,
            "stopped_at": self._stopped_at,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "batches_processed": self._batches,
            "batch_size": self._batch_size,
            "errors": self._errors,
            "last_error": self._last_error,
            "interface": interface.status() if interface is not None else None,
            "pipeline": self._pipeline.status(),
        }
