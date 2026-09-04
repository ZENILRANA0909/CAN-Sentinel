"""WebSocket streaming.

These tests are synchronous because Starlette's ``TestClient`` drives the
WebSocket handshake on its own event loop; mixing that with an async test would
deadlock.
"""

from __future__ import annotations

import json
import time
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.broadcaster import Broadcaster, EventType


@pytest.fixture
def sync_client(settings: Settings):
    """A TestClient with the application lifespan running."""
    with TestClient(create_app(settings)) as client:
        yield client


def drain(websocket, *, seconds: float, stop_on: str | None = None) -> Counter[str]:
    """Collect event types seen within a time budget."""
    seen: Counter[str] = Counter()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        message = websocket.receive_json()
        seen[message["event"]] += 1
        if stop_on and message["event"] == stop_on:
            break
    return seen


class TestHandshake:
    def test_seeds_the_client_with_a_status_snapshot(self, sync_client: TestClient) -> None:
        """A dashboard must render immediately, not after the first tick."""
        with sync_client.websocket_connect("/ws/traffic") as websocket:
            first = websocket.receive_json()
        assert first["event"] == EventType.SYSTEM_STATUS.value
        assert "monitor" in first["data"]
        assert "detection" in first["data"]

    def test_envelope_shape_is_consistent(self, sync_client: TestClient) -> None:
        with sync_client.websocket_connect("/ws/traffic") as websocket:
            envelope = websocket.receive_json()
        assert set(envelope) == {"event", "timestamp", "sequence", "data"}

    def test_client_is_registered_and_deregistered(self, sync_client: TestClient) -> None:
        assert sync_client.get("/api/status").json()["websocket"]["clients"] == 0
        with sync_client.websocket_connect("/ws/traffic") as websocket:
            websocket.receive_json()
            assert sync_client.get("/api/status").json()["websocket"]["clients"] == 1
        # Give the server a moment to finish tearing the connection down.
        for _ in range(50):
            if sync_client.get("/api/status").json()["websocket"]["clients"] == 0:
                break
            time.sleep(0.02)
        assert sync_client.get("/api/status").json()["websocket"]["clients"] == 0

    def test_multiple_clients_are_supported(self, sync_client: TestClient) -> None:
        with sync_client.websocket_connect("/ws/traffic") as first:
            first.receive_json()
            with sync_client.websocket_connect("/ws/traffic") as second:
                second.receive_json()
                assert sync_client.get("/api/status").json()["websocket"]["clients"] == 2


class TestClientCommands:
    def test_ping_is_answered(self, sync_client: TestClient) -> None:
        with sync_client.websocket_connect("/ws/traffic") as websocket:
            websocket.receive_json()
            websocket.send_json({"action": "ping", "id": 42})
            while True:
                message = websocket.receive_json()
                if message["event"] == "PONG":
                    assert message["data"]["echo"] == 42
                    break

    def test_status_can_be_requested_on_demand(self, sync_client: TestClient) -> None:
        with sync_client.websocket_connect("/ws/traffic") as websocket:
            websocket.receive_json()
            websocket.send_json({"action": "status"})
            message = websocket.receive_json()
            assert message["event"] == EventType.SYSTEM_STATUS.value

    def test_unknown_action_returns_an_error_without_dropping_the_socket(
        self, sync_client: TestClient
    ) -> None:
        with sync_client.websocket_connect("/ws/traffic") as websocket:
            websocket.receive_json()
            websocket.send_json({"action": "definitely-not-real"})
            seen = drain(websocket, seconds=5.0, stop_on="ERROR")
            assert seen["ERROR"] == 1

            # The connection still works afterwards.
            websocket.send_json({"action": "ping"})
            assert drain(websocket, seconds=5.0, stop_on="PONG")["PONG"] == 1

    def test_malformed_json_is_answered_with_an_error(self, sync_client: TestClient) -> None:
        with sync_client.websocket_connect("/ws/traffic") as websocket:
            websocket.receive_json()
            websocket.send_text("this is not json")
            assert drain(websocket, seconds=5.0, stop_on="ERROR")["ERROR"] == 1

    def test_non_object_json_is_rejected(self, sync_client: TestClient) -> None:
        with sync_client.websocket_connect("/ws/traffic") as websocket:
            websocket.receive_json()
            websocket.send_text(json.dumps([1, 2, 3]))
            assert drain(websocket, seconds=5.0, stop_on="ERROR")["ERROR"] == 1

    def test_oversized_frame_is_rejected(self, sync_client: TestClient) -> None:
        with sync_client.websocket_connect("/ws/traffic") as websocket:
            websocket.receive_json()
            websocket.send_text("x" * 5000)
            assert drain(websocket, seconds=5.0, stop_on="ERROR")["ERROR"] == 1


class TestEventStream:
    def test_traffic_and_status_events_are_pushed(self, sync_client: TestClient) -> None:
        with sync_client.websocket_connect("/ws/traffic") as websocket:
            websocket.receive_json()
            sync_client.post("/api/simulation/start", json={"mode": "NORMAL"})
            seen = drain(websocket, seconds=4.0)
            sync_client.post("/api/simulation/stop")

        assert seen[EventType.SIMULATION_STATUS.value] >= 1
        assert seen[EventType.CAN_MESSAGE.value] >= 1
        assert seen[EventType.TRAFFIC_RATE_UPDATE.value] >= 1

    def test_attacks_are_broadcast_as_they_are_detected(self, sync_client: TestClient) -> None:
        with sync_client.websocket_connect("/ws/traffic") as websocket:
            websocket.receive_json()
            sync_client.post(
                "/api/simulation/start", json={"mode": "FAKE_SPEED", "fake_speed_value": 255.0}
            )
            alert = None
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                message = websocket.receive_json()
                if message["event"] == EventType.ATTACK_DETECTED.value:
                    alert = message["data"]
                    break
            sync_client.post("/api/simulation/stop")

        assert alert is not None, "no ATTACK_DETECTED event was broadcast"
        assert alert["attack_type"] in {"FAKE_SPEED", "FREQUENCY_ANOMALY"}
        assert alert["severity"] in {"MEDIUM", "HIGH", "CRITICAL"}
        assert alert["evidence"]

    def test_can_message_batches_report_sampling(self, sync_client: TestClient) -> None:
        with sync_client.websocket_connect("/ws/traffic") as websocket:
            websocket.receive_json()
            sync_client.post(
                "/api/simulation/start", json={"mode": "CAN_FLOOD", "flood_rate": 2000.0}
            )
            batch = None
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                message = websocket.receive_json()
                if message["event"] == EventType.CAN_MESSAGE.value and message["data"]["sampled"]:
                    batch = message["data"]
                    break
            sync_client.post("/api/simulation/stop")

        assert batch is not None, "flood never produced a sampled batch"
        # The stream is capped, but the true observed count is still reported.
        assert batch["count"] <= 40
        assert batch["observed"] > batch["count"]

    def test_configuration_changes_are_broadcast(self, sync_client: TestClient) -> None:
        with sync_client.websocket_connect("/ws/traffic") as websocket:
            websocket.receive_json()
            sync_client.put("/api/config", json={"detection": {"fake_speed_threshold": 190.0}})
            seen = drain(websocket, seconds=5.0, stop_on=EventType.CONFIG_UPDATED.value)
        assert seen[EventType.CONFIG_UPDATED.value] == 1


class TestBroadcasterUnit:
    async def test_rejects_clients_beyond_capacity(self) -> None:
        class FakeSocket:
            async def send_text(self, data: str) -> None:
                return None

            async def close(self, code: int = 1000) -> None:
                return None

        broadcaster = Broadcaster(max_clients=1)
        await broadcaster.start()
        try:
            assert await broadcaster.connect(FakeSocket()) is not None
            assert await broadcaster.connect(FakeSocket()) is None
        finally:
            await broadcaster.stop()

    async def test_publish_with_no_clients_is_a_no_op(self) -> None:
        broadcaster = Broadcaster()
        assert broadcaster.publish(EventType.SYSTEM_STATUS, {"a": 1}) == 0

    async def test_buffer_keeps_only_the_newest_frames(self) -> None:
        broadcaster = Broadcaster(max_messages_per_flush=5)
        broadcaster.queue_messages([{"n": index} for index in range(20)])
        # Flushing with no clients still clears the buffer.
        assert broadcaster.flush_messages() == 0
        assert broadcaster.status()["buffered_messages"] == 0

    async def test_slow_client_drops_frames_instead_of_blocking(self) -> None:
        """One lagging dashboard must never stall the pipeline."""

        class SilentSocket:
            async def send_text(self, data: str) -> None:
                # Never drains; the queue will fill.
                import asyncio

                await asyncio.sleep(3600)

            async def close(self, code: int = 1000) -> None:
                return None

        broadcaster = Broadcaster(client_queue_size=10)
        await broadcaster.start()
        try:
            client = await broadcaster.connect(SilentSocket())
            assert client is not None
            for index in range(100):
                broadcaster.publish(EventType.SYSTEM_STATUS, {"n": index})
            assert client.dropped > 0
            assert client.queue.qsize() <= 10
        finally:
            await broadcaster.stop()

    async def test_unserialisable_payload_does_not_raise(self) -> None:
        broadcaster = Broadcaster()
        # `default=str` handles it, but the encoder must never propagate.
        assert broadcaster.publish(EventType.SYSTEM_STATUS, {"obj": object()}) == 0
