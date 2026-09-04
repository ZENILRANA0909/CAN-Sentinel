"""WebSocket fan-out.

Two delivery paths, deliberately different:

* **Security and status events** are published immediately.  An attack alert
  that arrives a quarter of a second late is a worse product.
* **Raw CAN frames** are buffered and flushed on a timer, carrying a sample of
  the frames seen plus the true count.  Under a 2000 msg/s flood, pushing every
  frame would saturate the socket and lock up the browser; the dashboard needs
  a readable stream and an accurate rate, which is exactly what it gets.

Each client has its own bounded queue and its own sender task, so one slow
consumer can never stall the pipeline or the other clients.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol

from app.core.logging import get_logger

logger = get_logger("services.broadcaster")


class EventType(str, Enum):
    """Every event kind that can appear on ``/ws/traffic``."""

    CAN_MESSAGE = "CAN_MESSAGE"
    ATTACK_DETECTED = "ATTACK_DETECTED"
    TRAFFIC_RATE_UPDATE = "TRAFFIC_RATE_UPDATE"
    SYSTEM_STATUS = "SYSTEM_STATUS"
    SIMULATION_STATUS = "SIMULATION_STATUS"
    MONITOR_STATUS = "MONITOR_STATUS"
    CONFIG_UPDATED = "CONFIG_UPDATED"


class WebSocketLike(Protocol):
    """Structural type for the bits of ``fastapi.WebSocket`` used here."""

    async def send_text(self, data: str) -> None: ...
    async def close(self, code: int = 1000) -> None: ...


class ClientConnection:
    """One connected dashboard, with its own outbound queue and sender task."""

    def __init__(self, websocket: WebSocketLike, *, queue_size: int, client_id: str) -> None:
        self.websocket = websocket
        self.client_id = client_id
        self.connected_at = time.time()
        self.sent = 0
        self.dropped = 0
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=queue_size)
        self.task: asyncio.Task[None] | None = None
        self.closed = asyncio.Event()

    def offer(self, payload: str) -> None:
        """Enqueue without blocking; drop the oldest frame if the client lags."""
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):  # race with the sender
                self.queue.get_nowait()
            self.dropped += 1
            try:
                self.queue.put_nowait(payload)
            except asyncio.QueueFull:  # pragma: no cover - race
                self.dropped += 1

    async def run(self) -> None:
        """Drain this client's queue until it disconnects or errors."""
        try:
            while True:
                payload = await self.queue.get()
                await self.websocket.send_text(payload)
                self.sent += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info(
                "WebSocket client send loop ended",
                extra={"context": {"client_id": self.client_id, "reason": str(exc)}},
            )
        finally:
            self.closed.set()

    def stats(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "connected_at": self.connected_at,
            "connected_seconds": round(time.time() - self.connected_at, 1),
            "sent": self.sent,
            "dropped": self.dropped,
            "queued": self.queue.qsize(),
        }


class Broadcaster:
    """Owns the connected clients and the CAN-frame flush ticker."""

    def __init__(
        self,
        *,
        flush_interval_ms: int = 250,
        max_messages_per_flush: int = 40,
        max_clients: int = 32,
        client_queue_size: int = 200,
    ) -> None:
        self._flush_interval = max(0.05, flush_interval_ms / 1000.0)
        self._max_messages = max(1, max_messages_per_flush)
        self._max_clients = max(1, max_clients)
        self._client_queue_size = max(10, client_queue_size)

        self._clients: dict[str, ClientConnection] = {}
        self._buffer: list[dict[str, Any]] = []
        self._buffered_total = 0
        self._ticker: asyncio.Task[None] | None = None
        self._running = False
        self._sequence = 0
        self._published = 0
        self._next_client_id = 0

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._ticker = asyncio.create_task(self._flush_loop(), name="can-sentinel-ws-flush")
        logger.info("Broadcaster started")

    async def stop(self) -> None:
        """Stop the ticker and close every client cleanly."""
        self._running = False
        ticker, self._ticker = self._ticker, None
        if ticker is not None:
            ticker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ticker
        for client in list(self._clients.values()):
            await self.disconnect(client, code=1001)
        self._buffer.clear()
        self._buffered_total = 0
        logger.info("Broadcaster stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # ------------------------------------------------------------------ #
    # Client management                                                  #
    # ------------------------------------------------------------------ #
    async def connect(self, websocket: WebSocketLike) -> ClientConnection | None:
        """Register a client, or return ``None`` when at capacity."""
        if len(self._clients) >= self._max_clients:
            logger.warning(
                "Rejecting WebSocket client: capacity reached",
                extra={"context": {"max_clients": self._max_clients}},
            )
            return None
        self._next_client_id += 1
        client = ClientConnection(
            websocket, queue_size=self._client_queue_size, client_id=f"ws-{self._next_client_id}"
        )
        self._clients[client.client_id] = client
        client.task = asyncio.create_task(client.run(), name=f"can-sentinel-{client.client_id}")
        logger.info(
            "WebSocket client connected",
            extra={"context": {"client_id": client.client_id, "clients": len(self._clients)}},
        )
        return client

    async def disconnect(self, client: ClientConnection, *, code: int = 1000) -> None:
        """Deregister a client and tear down its sender task."""
        self._clients.pop(client.client_id, None)
        task, client.task = client.task, None
        if task is not None and not task.done():
            task.cancel()
            # Errors here were already logged by run(); the client is going away.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        with contextlib.suppress(Exception):  # the socket may already be gone
            await client.websocket.close(code=code)
        logger.info(
            "WebSocket client disconnected",
            extra={"context": {"client_id": client.client_id, "clients": len(self._clients)}},
        )

    # ------------------------------------------------------------------ #
    # Publishing                                                         #
    # ------------------------------------------------------------------ #
    def publish(self, event: EventType, data: dict[str, Any]) -> int:
        """Send an event to every client immediately. Returns the client count."""
        if not self._clients:
            return 0
        payload = self._encode(event, data)
        for client in list(self._clients.values()):
            client.offer(payload)
        self._published += 1
        return len(self._clients)

    def queue_messages(self, messages: list[dict[str, Any]]) -> None:
        """Buffer CAN frames for the next timed flush.

        The buffer keeps the *most recent* frames: during a flood the newest
        traffic is what an operator needs to see.
        """
        if not messages:
            return
        self._buffered_total += len(messages)
        self._buffer.extend(messages)
        if len(self._buffer) > self._max_messages:
            self._buffer = self._buffer[-self._max_messages :]

    async def _flush_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)
                self.flush_messages()
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - defensive
                logger.error("Broadcaster flush failed", exc_info=True)

    def flush_messages(self) -> int:
        """Emit the buffered frame sample as a single ``CAN_MESSAGE`` event."""
        if not self._buffer:
            self._buffered_total = 0
            return 0
        messages, self._buffer = self._buffer, []
        observed, self._buffered_total = self._buffered_total, 0
        if not self._clients:
            return 0
        self.publish(
            EventType.CAN_MESSAGE,
            {
                "messages": messages,
                "count": len(messages),
                "observed": observed,
                "sampled": observed > len(messages),
                "interval_ms": round(self._flush_interval * 1000),
            },
        )
        return len(messages)

    # ------------------------------------------------------------------ #
    def _encode(self, event: EventType, data: dict[str, Any]) -> str:
        self._sequence += 1
        envelope = {
            "event": event.value,
            "timestamp": datetime.now(UTC).isoformat(),
            "sequence": self._sequence,
            "data": data,
        }
        try:
            return json.dumps(envelope, default=str)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            logger.error("Failed to encode event", extra={"context": {"error": str(exc)}})
            return json.dumps(
                {
                    "event": event.value,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "sequence": self._sequence,
                    "data": {"error": "event could not be serialised"},
                }
            )

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "clients": len(self._clients),
            "max_clients": self._max_clients,
            "events_published": self._published,
            "flush_interval_ms": round(self._flush_interval * 1000),
            "max_messages_per_flush": self._max_messages,
            "buffered_messages": len(self._buffer),
            "connections": [client.stats() for client in self._clients.values()],
        }
