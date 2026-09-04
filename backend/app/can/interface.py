"""CAN interface abstraction.

The rest of CAN-Sentinel never imports a driver directly.  It receives a
:class:`BaseCanInterface` and calls :meth:`~BaseCanInterface.receive` - whether
the frames originate from the built-in simulator, a physical adapter driven by
``python-can``, or a deterministic mock inside the test-suite.
"""

from __future__ import annotations

import abc
import asyncio
import contextlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.can.message import CanMessage
from app.core.logging import get_logger

logger = get_logger("can.interface")


class InterfaceState(str, Enum):
    """Lifecycle state of a CAN interface."""

    CLOSED = "CLOSED"
    OPENING = "OPENING"
    OPEN = "OPEN"
    ERROR = "ERROR"


@dataclass
class InterfaceStats:
    """Counters describing traffic that crossed an interface."""

    received: int = 0
    sent: int = 0
    dropped: int = 0
    errors: int = 0
    last_error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "received": self.received,
            "sent": self.sent,
            "dropped": self.dropped,
            "errors": self.errors,
            "last_error": self.last_error,
            **self.extra,
        }


class BaseCanInterface(abc.ABC):
    """Common lifecycle, buffering and statistics for every CAN backend."""

    #: Short backend identifier reported through the API.
    backend: str = "base"

    def __init__(
        self, *, channel: str = "vcan0", bitrate: int = 500_000, queue_size: int = 20_000
    ) -> None:
        if queue_size < 1:
            raise ValueError("queue_size must be at least 1")
        self.channel = channel
        self.bitrate = bitrate
        self.queue_size = queue_size
        self._queue: asyncio.Queue[CanMessage] = asyncio.Queue(maxsize=queue_size)
        self._state = InterfaceState.CLOSED
        self._stats = InterfaceStats()

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #
    async def open(self) -> None:
        """Open the underlying bus. Idempotent."""
        if self._state is InterfaceState.OPEN:
            return
        self._state = InterfaceState.OPENING
        try:
            await self._open()
        except Exception as exc:
            self._state = InterfaceState.ERROR
            self._stats.errors += 1
            self._stats.last_error = str(exc)
            raise
        self._state = InterfaceState.OPEN
        logger.info(
            "CAN interface opened",
            extra={"context": {"backend": self.backend, "channel": self.channel}},
        )

    async def close(self) -> None:
        """Close the underlying bus and drop any buffered frames. Idempotent."""
        if self._state is InterfaceState.CLOSED:
            return
        try:
            await self._close()
        finally:
            self._state = InterfaceState.CLOSED
            self.drain()
            logger.info(
                "CAN interface closed",
                extra={"context": {"backend": self.backend, "channel": self.channel}},
            )

    @abc.abstractmethod
    async def _open(self) -> None:
        """Backend specific open."""

    @abc.abstractmethod
    async def _close(self) -> None:
        """Backend specific close."""

    @abc.abstractmethod
    async def send(self, message: CanMessage) -> None:
        """Transmit a frame onto the bus."""

    # ------------------------------------------------------------------ #
    # Receiving                                                          #
    # ------------------------------------------------------------------ #
    async def receive(self, timeout: float | None = 0.5) -> CanMessage | None:
        """Return the next frame, or ``None`` if none arrived within ``timeout``."""
        if timeout is None:
            message = await self._queue.get()
            self._stats.received += 1
            return message
        try:
            message = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            return None
        self._stats.received += 1
        return message

    async def receive_batch(self, max_items: int, timeout: float = 0.25) -> list[CanMessage]:
        """Return up to ``max_items`` frames, blocking at most ``timeout`` for the first.

        Batching keeps the receive loop cheap under flood conditions: one await
        per batch instead of one await per frame.
        """
        first = await self.receive(timeout=timeout)
        if first is None:
            return []
        batch = [first]
        while len(batch) < max_items:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
            else:
                self._stats.received += 1
        return batch

    def _enqueue(self, message: CanMessage) -> bool:
        """Buffer an inbound frame, discarding the oldest entry when full.

        Dropping the oldest frame keeps the monitor current during a flood
        rather than stalling the producer, and the drop is always counted.
        """
        try:
            self._queue.put_nowait(message)
            return True
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):  # race with a consumer
                self._queue.get_nowait()
            self._stats.dropped += 1
            try:
                self._queue.put_nowait(message)
            except asyncio.QueueFull:  # pragma: no cover - race with a producer
                return False
            return True

    def drain(self) -> int:
        """Discard every buffered frame and return how many were dropped."""
        count = 0
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            count += 1
        return count

    # ------------------------------------------------------------------ #
    # Introspection                                                      #
    # ------------------------------------------------------------------ #
    @property
    def state(self) -> InterfaceState:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state is InterfaceState.OPEN

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    @property
    def stats(self) -> InterfaceStats:
        return self._stats

    def status(self) -> dict[str, Any]:
        """Serialisable interface status for ``/api/status``."""
        return {
            "backend": self.backend,
            "channel": self.channel,
            "bitrate": self.bitrate,
            "state": self._state.value,
            "is_open": self.is_open,
            "queue_size": self.queue_size,
            "queue_pending": self.pending,
            "statistics": self._stats.as_dict(),
        }

    async def __aenter__(self) -> BaseCanInterface:
        await self.open()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()
