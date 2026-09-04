"""Real-time WebSocket endpoint.

``/ws/traffic`` is a push channel.  Clients are not required to send anything;
those that do get a ``ping`` -> ``pong`` reply and can request an immediate
status snapshot.  Anything else is answered with an error frame rather than
dropping the connection, so a misbehaving client cannot take down its own feed
or anyone else's.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import get_state
from app.core.logging import get_logger
from app.services.broadcaster import EventType

logger = get_logger("api.websocket")

router = APIRouter(tags=["websocket"])

#: Refuse client frames larger than this; nothing legitimate approaches it.
MAX_CLIENT_FRAME_BYTES = 4096
CLOSE_CAPACITY = 1013  # "try again later"


@router.websocket("/ws/traffic")
async def traffic_stream(websocket: WebSocket) -> None:
    """Stream CAN traffic, security events and status updates to a dashboard."""
    state = get_state(websocket)  # type: ignore[arg-type]
    await websocket.accept()

    client = await state.broadcaster.connect(websocket)
    if client is None:
        await websocket.close(code=CLOSE_CAPACITY, reason="server at client capacity")
        return

    # Seed the client so the dashboard renders immediately instead of waiting
    # for the first periodic tick.
    try:
        await websocket.send_text(
            json.dumps(
                {
                    "event": EventType.SYSTEM_STATUS.value,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "sequence": 0,
                    "data": state.status(),
                },
                default=str,
            )
        )
    except Exception:  # pragma: no cover - client vanished during the handshake
        await state.broadcaster.disconnect(client)
        return

    try:
        while True:
            raw = await websocket.receive_text()
            await _handle_client_frame(websocket, state, raw)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:  # pragma: no cover - server shutdown
        raise
    except Exception as exc:
        logger.info(
            "WebSocket receive loop ended",
            extra={"context": {"client_id": client.client_id, "reason": str(exc)}},
        )
    finally:
        await state.broadcaster.disconnect(client)


async def _handle_client_frame(websocket: WebSocket, state: Any, raw: str) -> None:
    """Answer a client command. Never raises for bad input."""
    if len(raw) > MAX_CLIENT_FRAME_BYTES:
        await _send(websocket, "ERROR", {"error": "frame too large"})
        return
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        await _send(websocket, "ERROR", {"error": "expected a JSON object"})
        return
    if not isinstance(payload, dict):
        await _send(websocket, "ERROR", {"error": "expected a JSON object"})
        return

    action = str(payload.get("action", "")).lower()
    if action == "ping":
        await _send(websocket, "PONG", {"echo": payload.get("id")})
    elif action == "status":
        await _send(websocket, EventType.SYSTEM_STATUS.value, state.status())
    else:
        await _send(
            websocket,
            "ERROR",
            {"error": f"unknown action: {action or '(missing)'}", "supported": ["ping", "status"]},
        )


async def _send(websocket: WebSocket, event: str, data: dict[str, Any]) -> None:
    with contextlib.suppress(Exception):  # the socket may close mid-reply
        await websocket.send_text(
            json.dumps(
                {
                    "event": event,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "sequence": 0,
                    "data": data,
                },
                default=str,
            )
        )
