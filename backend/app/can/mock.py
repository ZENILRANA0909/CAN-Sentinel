"""Deterministic CAN interface used by the test-suite.

Unlike the virtual bus, the mock never invents timing: a test feeds an exact
sequence of frames and asserts on exactly what the pipeline did with them.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.can.interface import BaseCanInterface
from app.can.message import CanMessage
from app.core.exceptions import CanInterfaceError


class MockCanInterface(BaseCanInterface):
    """A scriptable CAN interface with a recorded transmit log."""

    backend = "mock"

    def __init__(self, *, messages: Iterable[CanMessage] | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.sent_messages: list[CanMessage] = []
        self.open_calls = 0
        self.close_calls = 0
        self.fail_on_open = False
        self.fail_on_send = False
        for message in messages or ():
            self._enqueue(message)

    async def _open(self) -> None:
        self.open_calls += 1
        if self.fail_on_open:
            raise CanInterfaceError("mock interface configured to fail on open")

    async def _close(self) -> None:
        self.close_calls += 1

    async def send(self, message: CanMessage) -> None:
        if self.fail_on_send:
            self._stats.errors += 1
            raise CanInterfaceError("mock interface configured to fail on send")
        if not self.is_open:
            raise CanInterfaceError("cannot transmit on a closed mock CAN interface")
        self.sent_messages.append(message)
        self._stats.sent += 1
        self._enqueue(message)

    # ------------------------------------------------------------------ #
    # Test helpers                                                       #
    # ------------------------------------------------------------------ #
    def feed(self, *messages: CanMessage) -> None:
        """Queue frames as though they had arrived from the bus."""
        for message in messages:
            self._enqueue(message)

    def feed_many(self, messages: Iterable[CanMessage]) -> None:
        for message in messages:
            self._enqueue(message)
