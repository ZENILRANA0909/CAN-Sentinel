"""In-process virtual CAN bus.

This is the backend that makes CAN-Sentinel demonstrable on a laptop with no
CAN hardware attached.  It behaves like a loopback bus: whatever the simulator
transmits with :meth:`send` is delivered to whoever is calling :meth:`receive`,
with the same bounded-queue and back-pressure semantics as a real adapter.
"""

from __future__ import annotations

from app.can.interface import BaseCanInterface
from app.can.message import CanMessage
from app.core.exceptions import CanInterfaceError


class VirtualCanInterface(BaseCanInterface):
    """A loopback CAN bus living entirely inside the process."""

    backend = "virtual"

    async def _open(self) -> None:
        # Nothing to acquire - the queue created in __init__ *is* the bus.
        return None

    async def _close(self) -> None:
        return None

    async def send(self, message: CanMessage) -> None:
        """Publish a frame onto the virtual bus."""
        if not self.is_open:
            raise CanInterfaceError(
                "cannot transmit on a closed virtual CAN interface",
                details={"channel": self.channel},
            )
        # Frames are stamped with the interface channel so downstream consumers
        # always report the bus the frame was actually seen on.
        if message.channel != self.channel:
            message = message.model_copy(update={"channel": self.channel})
        self._stats.sent += 1
        self._enqueue(message)

    async def send_many(self, messages: list[CanMessage]) -> int:
        """Publish a burst of frames, returning how many were accepted."""
        accepted = 0
        for message in messages:
            await self.send(message)
            accepted += 1
        return accepted
