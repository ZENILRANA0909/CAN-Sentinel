"""Shared test fixtures.

Every test gets a fully isolated application: its own in-memory database, its
own services, its own CAN interface. Nothing is shared at module scope, so
tests cannot leak state into one another and can run in any order.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.can.message import CanMessage, MessageSource
from app.can.mock import MockCanInterface
from app.can.signals import encode_vehicle_speed
from app.core.config import Settings
from app.core.runtime_config import ConfigService
from app.detection.engine import DetectionEngine
from app.main import create_app
from app.models.base import Base
from app.services.state import ApplicationState
from app.storage.database import Database


@pytest.fixture
def settings() -> Settings:
    """Settings suitable for a fast, isolated test run."""
    return Settings(
        app_env="testing",
        database_url="sqlite:///:memory:",
        log_to_file=False,
        log_level="CRITICAL",
        monitor_autostart=False,
        simulator_autostart=False,
        retention_enabled=False,
        can_interface="virtual",
        can_channel="vcan-test",
        # Fast flush intervals keep tests from waiting on background timers.
        db_write_interval_seconds=0.05,
        ws_flush_interval_ms=50,
        # Throttling off by default so unit tests observe every verdict. Tests
        # that measure behaviour under sustained load set a realistic cooldown
        # themselves, because unthrottled event emission is not how the product
        # actually runs.
        detection_event_cooldown_seconds=0.0,
    )


@pytest.fixture
def config_service(settings: Settings) -> ConfigService:
    return ConfigService.from_settings(settings)


@pytest.fixture
def engine(config_service: ConfigService) -> DetectionEngine:
    return DetectionEngine(config_service)


@pytest.fixture
def database() -> Iterator[Database]:
    """A connected in-memory database with the schema applied."""
    db = Database("sqlite:///:memory:")
    db.init_schema()
    try:
        yield db
    finally:
        Base.metadata.drop_all(db.engine)
        db.dispose()


@pytest.fixture
async def app_state(settings: Settings) -> AsyncIterator[ApplicationState]:
    """A started ApplicationState with every background service running."""
    state = ApplicationState(settings)
    await state.startup()
    try:
        yield state
    finally:
        await state.shutdown()


@pytest.fixture
async def api_app(settings: Settings) -> AsyncIterator[FastAPI]:
    """A FastAPI application with its lifespan run, ready for requests."""
    application = create_app(settings)
    async with LifespanRunner(application):
        yield application


@pytest.fixture
async def client(api_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An httpx client bound to the test application."""
    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


class LifespanRunner:
    """Run a FastAPI app's lifespan around a block."""

    def __init__(self, application: FastAPI) -> None:
        self.application = application
        self._manager = None

    async def __aenter__(self) -> FastAPI:
        self._manager = self.application.router.lifespan_context(self.application)
        await self._manager.__aenter__()
        return self.application

    async def __aexit__(self, *exc: object) -> None:
        assert self._manager is not None
        await self._manager.__aexit__(*exc)


# --------------------------------------------------------------------------- #
# Frame builders                                                              #
# --------------------------------------------------------------------------- #
@pytest.fixture
def mock_interface() -> MockCanInterface:
    return MockCanInterface(channel="vcan-test")


def make_message(
    *,
    can_id: int = 0x100,
    data: bytes = b"\x00" * 8,
    timestamp: float | None = None,
    source: MessageSource = MessageSource.SIMULATOR,
    channel: str = "vcan-test",
) -> CanMessage:
    """Build a valid frame with sensible defaults."""
    return CanMessage(
        timestamp=time.time() if timestamp is None else timestamp,
        arbitration_id=can_id,
        data=data,
        channel=channel,
        source=source,
    )


def make_speed_message(speed_kmh: float, timestamp: float, *, can_id: int = 0x300) -> CanMessage:
    """Build a vehicle-speed frame carrying an exact speed value."""
    return CanMessage(
        timestamp=timestamp,
        arbitration_id=can_id,
        data=encode_vehicle_speed(speed_kmh),
        channel="vcan-test",
    )


async def wait_for(predicate, *, timeout: float = 5.0, interval: float = 0.02) -> bool:
    """Poll ``predicate`` until it is true or the timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()
