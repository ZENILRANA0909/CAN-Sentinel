"""Physical CAN adapter backend built on ``python-can``.

``python-can`` is a blocking, thread-oriented library, so the bus is drained by
a dedicated daemon thread that hands frames back to the event loop with
``loop.call_soon_threadsafe``.  From the pipeline's point of view this backend
is indistinguishable from the virtual bus.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from app.can.interface import BaseCanInterface
from app.can.message import CanMessage, MessageSource
from app.core.exceptions import CanInterfaceError
from app.core.logging import get_logger

logger = get_logger("can.python_can")

#: How long the reader thread blocks in ``bus.recv`` before re-checking the
#: stop flag. Keeps shutdown responsive without busy-waiting.
RECV_POLL_SECONDS = 0.2
SHUTDOWN_JOIN_SECONDS = 3.0


class PythonCanInterface(BaseCanInterface):
    """Adapter around a real ``can.BusABC`` instance."""

    backend = "python-can"

    def __init__(
        self,
        *,
        channel: str = "can0",
        bitrate: int = 500_000,
        bustype: str = "socketcan",
        queue_size: int = 20_000,
        extra_bus_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(channel=channel, bitrate=bitrate, queue_size=queue_size)
        self.bustype = bustype
        self._extra_bus_kwargs = extra_bus_kwargs or {}
        self._bus: Any | None = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #
    async def _open(self) -> None:
        try:
            import can
        except ImportError as exc:  # pragma: no cover - python-can is a hard dependency
            raise CanInterfaceError(
                "python-can is not installed; set CAN_INTERFACE=virtual to use the simulator"
            ) from exc

        self._loop = asyncio.get_running_loop()
        self._stop.clear()

        def _build_bus() -> Any:
            return can.interface.Bus(
                channel=self.channel,
                interface=self.bustype,
                bitrate=self.bitrate,
                **self._extra_bus_kwargs,
            )

        try:
            self._bus = await asyncio.to_thread(_build_bus)
        except Exception as exc:
            raise CanInterfaceError(
                f"could not open CAN channel {self.channel!r} via {self.bustype!r}: {exc}",
                details={"channel": self.channel, "bustype": self.bustype},
            ) from exc

        self._reader = threading.Thread(
            target=self._read_loop, name="can-sentinel-canrx", daemon=True
        )
        self._reader.start()

    async def _close(self) -> None:
        self._stop.set()
        reader, self._reader = self._reader, None
        if reader is not None and reader.is_alive():
            await asyncio.to_thread(reader.join, SHUTDOWN_JOIN_SECONDS)
        bus, self._bus = self._bus, None
        if bus is not None:
            try:
                await asyncio.to_thread(bus.shutdown)
            except Exception as exc:  # pragma: no cover - driver dependent
                logger.warning(
                    "Error shutting down CAN bus", extra={"context": {"error": str(exc)}}
                )
        self._loop = None

    # ------------------------------------------------------------------ #
    # Reader thread                                                      #
    # ------------------------------------------------------------------ #
    def _read_loop(self) -> None:
        bus, loop = self._bus, self._loop
        if bus is None or loop is None:  # pragma: no cover - defensive
            return
        while not self._stop.is_set():
            try:
                raw = bus.recv(timeout=RECV_POLL_SECONDS)
            except Exception as exc:  # pragma: no cover - driver dependent
                self._stats.errors += 1
                self._stats.last_error = str(exc)
                logger.error("CAN receive failed", extra={"context": {"error": str(exc)}})
                self._stop.wait(RECV_POLL_SECONDS)
                continue
            if raw is None:
                continue
            try:
                message = CanMessage.from_python_can(
                    raw, channel=self.channel, source=MessageSource.HARDWARE
                )
            except Exception as exc:
                # A malformed frame must never take down the reader thread.
                self._stats.errors += 1
                self._stats.last_error = str(exc)
                logger.warning(
                    "Discarded malformed CAN frame", extra={"context": {"error": str(exc)}}
                )
                continue
            try:
                loop.call_soon_threadsafe(self._enqueue, message)
            except RuntimeError:  # pragma: no cover - loop closed during shutdown
                break

    # ------------------------------------------------------------------ #
    # Transmit                                                           #
    # ------------------------------------------------------------------ #
    async def send(self, message: CanMessage) -> None:
        bus = self._bus
        if bus is None or not self.is_open:
            raise CanInterfaceError("cannot transmit on a closed python-can interface")
        try:
            await asyncio.to_thread(bus.send, message.to_python_can())
        except Exception as exc:
            self._stats.errors += 1
            self._stats.last_error = str(exc)
            raise CanInterfaceError(f"CAN transmit failed: {exc}") from exc
        self._stats.sent += 1

    def status(self) -> dict[str, Any]:
        payload = super().status()
        payload["bustype"] = self.bustype
        return payload
