"""Construction of the configured CAN backend."""

from __future__ import annotations

from app.can.interface import BaseCanInterface
from app.can.mock import MockCanInterface
from app.can.python_can import PythonCanInterface
from app.can.virtual import VirtualCanInterface
from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger

logger = get_logger("can.factory")


def create_can_interface(settings: Settings) -> BaseCanInterface:
    """Build the CAN interface selected by ``CAN_INTERFACE``.

    ``virtual`` (default) is the in-process loopback bus driven by the traffic
    simulator; ``python-can`` talks to a real adapter; ``mock`` is reserved for
    tests and produces no traffic on its own.
    """
    backend = settings.can_interface
    if backend == "virtual":
        return VirtualCanInterface(
            channel=settings.can_channel,
            bitrate=settings.can_bitrate,
            queue_size=settings.can_receive_queue_size,
        )
    if backend == "python-can":
        return PythonCanInterface(
            channel=settings.can_channel,
            bitrate=settings.can_bitrate,
            bustype=settings.can_bustype,
            queue_size=settings.can_receive_queue_size,
        )
    if backend == "mock":
        return MockCanInterface(
            channel=settings.can_channel,
            bitrate=settings.can_bitrate,
            queue_size=settings.can_receive_queue_size,
        )
    raise ConfigurationError(
        f"unsupported CAN interface backend: {backend!r}",
        details={"supported": ["virtual", "python-can", "mock"]},
    )
