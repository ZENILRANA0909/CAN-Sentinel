"""Application state container.

This is the composition root: one object that builds every service, wires the
dependencies together and owns startup and shutdown.  Routes reach it through
FastAPI dependencies rather than importing singletons, which is what lets the
test-suite construct a fully isolated application per test.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.can.factory import create_can_interface
from app.can.interface import BaseCanInterface
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.runtime_config import ConfigService, RuntimeConfig
from app.core.version import SERVICE_NAME, __version__
from app.detection.engine import DetectionEngine
from app.services.broadcaster import Broadcaster, EventType
from app.services.monitor import MonitorService
from app.services.pipeline import MessagePipeline
from app.services.simulation import SimulationService
from app.services.statistics import TrafficStatistics
from app.services.telemetry import TelemetryService
from app.simulation.modes import SimulationMode, SimulationProfile
from app.storage.database import Database
from app.storage.retention import RetentionService
from app.storage.writer import PersistenceWriter

logger = get_logger("services.state")


class ApplicationState:
    """Owns every long-lived service for one running application."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.started_at = time.time()
        self._started = False

        # --- Configuration ------------------------------------------------
        self.config_service = ConfigService.from_settings(settings)

        # --- Storage ------------------------------------------------------
        self.database = Database(
            settings.resolved_database_url, echo=settings.db_echo, sqlite_path=settings.sqlite_path
        )
        self.writer = PersistenceWriter(
            self.database,
            queue_size=settings.db_write_queue_size,
            batch_size=settings.db_write_batch_size,
            interval_seconds=settings.db_write_interval_seconds,
        )
        self.retention = RetentionService(
            self.database,
            self.config_service,
            interval_seconds=settings.retention_interval_seconds,
        )

        # --- Detection & live state ---------------------------------------
        self.engine = DetectionEngine(self.config_service)
        self.statistics = TrafficStatistics(window_seconds=settings.statistics_window_seconds)

        # --- Streaming ----------------------------------------------------
        self.broadcaster = Broadcaster(
            flush_interval_ms=settings.ws_flush_interval_ms,
            max_messages_per_flush=settings.ws_max_messages_per_flush,
            max_clients=settings.ws_max_clients,
            client_queue_size=settings.ws_client_queue_size,
        )

        # --- Pipeline -----------------------------------------------------
        self.pipeline = MessagePipeline(
            engine=self.engine,
            statistics=self.statistics,
            writer=self.writer,
            broadcaster=self.broadcaster,
            config_service=self.config_service,
            history_size=settings.history_buffer_size,
        )

        # --- Monitoring & simulation --------------------------------------
        self.monitor = MonitorService(
            interface_factory=self._build_interface,
            pipeline=self.pipeline,
            broadcaster=self.broadcaster,
            writer=self.writer,
        )
        self.simulation = SimulationService(
            monitor=self.monitor,
            broadcaster=self.broadcaster,
            writer=self.writer,
            statistics=self.statistics,
            default_profile=SimulationProfile(
                mode=SimulationMode.NORMAL,
                flood_rate=settings.simulator_flood_rate,
                fake_speed_value=settings.simulator_fake_speed_value,
            ),
            max_rate=settings.simulator_max_rate,
        )
        self.telemetry = TelemetryService(
            statistics=self.statistics,
            broadcaster=self.broadcaster,
            status_provider=self.status,
        )

        self.config_service.subscribe(self._on_config_changed)

    # ------------------------------------------------------------------ #
    # Interface construction                                             #
    # ------------------------------------------------------------------ #
    def _build_interface(self) -> BaseCanInterface:
        """Build a CAN interface from the *runtime* bus configuration."""
        can_config = self.config_service.current.can
        settings = self.settings.model_copy(
            update={
                "can_interface": can_config.interface,
                "can_channel": can_config.channel,
                "can_bitrate": can_config.bitrate,
            }
        )
        return create_can_interface(settings)

    def _on_config_changed(self, config: RuntimeConfig) -> None:
        self.broadcaster.publish(
            EventType.CONFIG_UPDATED,
            {"revision": self.config_service.revision, "config": config.model_dump(mode="json")},
        )

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #
    async def startup(self) -> None:
        """Bring every background service up, in dependency order."""
        if self._started:
            return
        self.database.init_schema()
        await self.writer.start()
        await self.retention.start()
        await self.broadcaster.start()
        await self.telemetry.start()

        self.writer.submit_system_event(
            event_type="APPLICATION_STARTED",
            message=f"{SERVICE_NAME} {__version__} started",
            context={
                "environment": self.settings.app_env,
                "can_interface": self.config_service.current.can.interface,
            },
        )

        if self.settings.monitor_autostart:
            try:
                await self.monitor.start()
            except Exception as exc:
                # A missing CAN adapter must not prevent the API from serving.
                logger.error(
                    "Monitor autostart failed; the API is still available",
                    extra={"context": {"error": str(exc)}},
                )

        if self.settings.simulator_autostart and self.monitor.is_running:
            try:
                await self.simulation.start()
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Simulator autostart failed", extra={"context": {"error": str(exc)}})

        self._started = True
        logger.info(
            "Application ready",
            extra={
                "context": {
                    "version": __version__,
                    "environment": self.settings.app_env,
                    "monitor_running": self.monitor.is_running,
                }
            },
        )

    async def shutdown(self) -> None:
        """Tear everything down in reverse order, tolerating partial startup."""
        logger.info("Application shutting down")
        for step, coroutine in (
            ("simulation", self.simulation.stop()),
            ("monitor", self.monitor.stop()),
            ("telemetry", self.telemetry.stop()),
            ("broadcaster", self.broadcaster.stop()),
            ("retention", self.retention.stop()),
        ):
            try:
                await coroutine
            except Exception as exc:  # pragma: no cover - best-effort shutdown
                logger.error(
                    f"Error stopping {step}", extra={"context": {"step": step, "error": str(exc)}}
                )

        self.writer.submit_system_event(
            event_type="APPLICATION_STOPPED", message=f"{SERVICE_NAME} stopped"
        )
        try:
            await self.writer.stop()
        except Exception as exc:  # pragma: no cover
            logger.error("Error stopping the writer", extra={"context": {"error": str(exc)}})
        self.database.dispose()
        self._started = False

    # ------------------------------------------------------------------ #
    # Status                                                             #
    # ------------------------------------------------------------------ #
    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.started_at

    def status(self) -> dict[str, Any]:
        """The composite status document behind ``GET /api/status``."""
        return {
            "service": SERVICE_NAME,
            "version": __version__,
            "environment": self.settings.app_env,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "started_at": self.started_at,
            "monitor": self.monitor.status(),
            "simulation": self.simulation.status(),
            "detection": self.engine.snapshot(),
            "traffic": self.statistics.traffic_snapshot(),
            "security": self.statistics.security_snapshot(),
            "websocket": self.broadcaster.status(),
            "storage": {
                "writer": self.writer.stats(),
                "retention": self.retention.status(),
                "connected": self.database.is_connected,
            },
            "telemetry": self.telemetry.status(),
            "config_revision": self.config_service.revision,
        }

    async def health(self) -> dict[str, Any]:
        """Liveness/readiness probe. The database check runs off the event loop."""
        database = await asyncio.to_thread(self.database.healthcheck)
        healthy = bool(database.get("healthy"))
        return {
            "status": "healthy" if healthy else "degraded",
            "service": SERVICE_NAME,
            "version": __version__,
            "environment": self.settings.app_env,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "checks": {
                "database": database,
                "monitor": {"running": self.monitor.is_running},
                "simulator": {"running": self.simulation.is_running},
                "writer": {"running": self.writer.is_running},
                "broadcaster": {"running": self.broadcaster.is_running},
            },
        }
