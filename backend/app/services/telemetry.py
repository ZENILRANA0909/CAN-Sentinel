"""Periodic telemetry ticker.

Samples the live statistics once a second and pushes a rate update to every
connected dashboard, plus a fuller system status on a slower cadence.  Running
this independently of the monitor means the UI keeps updating - showing a rate
of zero - even while monitoring is stopped, instead of appearing frozen.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

from app.core.logging import get_logger
from app.services.broadcaster import Broadcaster, EventType
from app.services.statistics import TrafficStatistics

logger = get_logger("services.telemetry")

DEFAULT_SAMPLE_INTERVAL = 1.0
DEFAULT_STATUS_INTERVAL = 5.0


class TelemetryService:
    """Drives the periodic WebSocket updates."""

    def __init__(
        self,
        *,
        statistics: TrafficStatistics,
        broadcaster: Broadcaster,
        status_provider: Callable[[], dict[str, Any]],
        sample_interval: float = DEFAULT_SAMPLE_INTERVAL,
        status_interval: float = DEFAULT_STATUS_INTERVAL,
    ) -> None:
        self._stats = statistics
        self._broadcaster = broadcaster
        self._status_provider = status_provider
        self._sample_interval = max(0.2, sample_interval)
        self._status_interval = max(self._sample_interval, status_interval)
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._ticks = 0

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="can-sentinel-telemetry")
        logger.info("Telemetry ticker started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        logger.info("Telemetry ticker stopped")

    async def _run(self) -> None:
        status_every = max(1, round(self._status_interval / self._sample_interval))
        while self._running:
            try:
                await asyncio.sleep(self._sample_interval)
                self._ticks += 1
                point = self._stats.sample()
                self._broadcaster.publish(
                    EventType.TRAFFIC_RATE_UPDATE,
                    {
                        **point,
                        "active_alerts": self._stats.active_alerts(),
                        "attacks_total": self._stats.attacks_total,
                        "threat_level": self._stats.threat_level().value,
                    },
                )
                if self._ticks % status_every == 0:
                    self._broadcaster.publish(EventType.SYSTEM_STATUS, self._status_provider())
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - defensive
                logger.error("Telemetry tick failed", exc_info=True)
                await asyncio.sleep(self._sample_interval)

    @property
    def is_running(self) -> bool:
        return self._running

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "ticks": self._ticks,
            "sample_interval_seconds": self._sample_interval,
            "status_interval_seconds": self._status_interval,
        }
