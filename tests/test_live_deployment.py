"""Black-box tests against a *running* CAN-Sentinel deployment.

The suite under ``backend/tests`` builds the application in-process. These
tests instead drive a real server over HTTP, which is what catches problems
that only appear once the thing is deployed: a broken reverse-proxy rule, a
service that starts but cannot write its database, or a proxy that mangles
the WebSocket upgrade.

They are skipped unless a target is supplied, so they never run by accident:

    # against a local dev server
    CAN_SENTINEL_URL=http://localhost:8000 pytest tests/ -v

    # against a production deployment, through a reverse proxy
    CAN_SENTINEL_URL=https://can-sentinel.example.com pytest tests/ -v

Requires ``httpx``; ``pip install -r backend/requirements-dev.txt`` provides it.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator

import pytest

httpx = pytest.importorskip("httpx", reason="httpx is required for the live deployment tests")

BASE_URL = os.environ.get("CAN_SENTINEL_URL", "").rstrip("/")

pytestmark = pytest.mark.skipif(
    not BASE_URL,
    reason="set CAN_SENTINEL_URL to the base URL of a running instance to enable these tests",
)

REQUEST_TIMEOUT = 30.0
DETECTION_TIMEOUT = 30.0


@pytest.fixture(scope="module")
def client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=f"{BASE_URL}/api", timeout=REQUEST_TIMEOUT) as http:
        yield http


@pytest.fixture(autouse=True)
def _clean_simulation(client: httpx.Client) -> Iterator[None]:
    """Leave the instance idle before and after every test."""
    client.post("/simulation/stop")
    yield
    client.post("/simulation/stop")


def poll_until(check, *, timeout: float = DETECTION_TIMEOUT, interval: float = 0.5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(interval)
    return False


def has_attack(client: httpx.Client, attack_type: str) -> bool:
    events = client.get("/attacks/recent", params={"limit": 50}).json()
    return any(event["attack_type"] == attack_type for event in events)


class TestDeployment:
    def test_health_endpoint_reports_a_working_database(self, client: httpx.Client) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert body["checks"]["database"]["healthy"] is True

    def test_openapi_documentation_is_served(self, client: httpx.Client) -> None:
        schema = httpx.get(f"{BASE_URL}/openapi.json", timeout=REQUEST_TIMEOUT).json()
        assert schema["info"]["title"] == "CAN-Sentinel"
        assert "/api/health" in schema["paths"]

    def test_dashboard_is_served_and_falls_back_for_client_routes(self) -> None:
        """Only meaningful behind the production proxy; skipped otherwise."""
        root = httpx.get(f"{BASE_URL}/", timeout=REQUEST_TIMEOUT, follow_redirects=True)
        if "text/html" not in root.headers.get("content-type", ""):
            pytest.skip("this target serves the API only, not the dashboard")
        assert root.status_code == 200
        # A deep link must return the SPA shell rather than a 404.
        deep = httpx.get(f"{BASE_URL}/security", timeout=REQUEST_TIMEOUT)
        assert deep.status_code == 200
        assert "text/html" in deep.headers["content-type"]

    def test_status_exposes_every_subsystem(self, client: httpx.Client) -> None:
        status = client.get("/status").json()
        for section in ("monitor", "simulation", "detection", "traffic", "security", "storage"):
            assert section in status
        assert len(status["detection"]["detectors"]) == 4


class TestLiveDetection:
    def test_normal_traffic_produces_no_new_alerts(self, client: httpx.Client) -> None:
        before = client.get("/attacks/statistics").json()["total_events"]
        client.post("/simulation/start", json={"mode": "NORMAL"})
        time.sleep(6)

        status = client.get("/status").json()
        assert status["traffic"]["current_rate_msg_per_s"] > 100
        after = client.get("/attacks/statistics").json()["total_events"]
        assert after == before, "a clean bus must not raise alerts"

    def test_fake_speed_is_detected_and_persisted(self, client: httpx.Client) -> None:
        client.post(
            "/simulation/start",
            json={"mode": "FAKE_SPEED", "fake_speed_value": 255.0, "fake_speed_rate": 100.0},
        )
        assert poll_until(lambda: has_attack(client, "FAKE_SPEED")), "no FAKE_SPEED event appeared"

        event = next(
            e for e in client.get("/attacks/recent", params={"limit": 50}).json()
            if e["attack_type"] == "FAKE_SPEED"
        )
        assert event["threat_level"] == "ATTACK"
        assert event["can_id_hex"] == "0x300"
        assert event["evidence"]["observed_speed_kmh"] == pytest.approx(255.0, abs=0.1)
        assert event["id"] is not None

    def test_flood_is_detected_without_losing_frames(self, client: httpx.Client) -> None:
        client.post("/simulation/start", json={"mode": "CAN_FLOOD", "flood_rate": 1500.0})
        assert poll_until(lambda: has_attack(client, "CAN_FLOOD")), "no CAN_FLOOD event appeared"

        status = client.get("/status").json()
        assert status["traffic"]["current_rate_msg_per_s"] > 600
        assert status["monitor"]["interface"]["statistics"]["dropped"] == 0
        assert status["storage"]["writer"]["messages_dropped"] == 0
        # Throttling must be doing its job at this rate.
        assert status["detection"]["events_suppressed"] > status["detection"]["events_emitted"]

    def test_injected_identifier_is_reported(self, client: httpx.Client) -> None:
        client.post("/monitor/start")
        for _ in range(6):
            client.post("/simulation/inject", json={"can_id": 0x123, "data": "DEADBEEF"})
            time.sleep(0.05)
        assert poll_until(
            lambda: any(
                e["attack_type"] == "ID_ANOMALY" and e["can_id"] == 0x123
                for e in client.get("/attacks/recent", params={"limit": 50}).json()
            )
        ), "the injected identifier was not reported"

    def test_detector_recovers_when_the_attack_stops(self, client: httpx.Client) -> None:
        client.post("/simulation/start", json={"mode": "CAN_FLOOD", "flood_rate": 1500.0})
        assert poll_until(lambda: has_attack(client, "CAN_FLOOD"))

        client.post("/simulation/mode", json={"mode": "NORMAL"})
        threshold = client.get("/config").json()["detection"]["flood_threshold"]

        def recovered() -> bool:
            status = client.get("/status").json()
            flood = next(
                d for d in status["detection"]["detectors"] if d["name"] == "can_flood"
            )
            return flood["state"]["current_rate_msg_per_s"] <= threshold

        assert poll_until(recovered, timeout=20), "the flood detector did not return to normal"

    def test_api_answers_promptly_under_flood(self, client: httpx.Client) -> None:
        """Real latency measurement - see docs/testing.md for why this belongs
        here rather than in the in-process suite."""
        client.post("/simulation/start", json={"mode": "CAN_FLOOD", "flood_rate": 2000.0})
        time.sleep(5)

        start = time.perf_counter()
        for _ in range(10):
            assert client.get("/health").status_code == 200
        elapsed = time.perf_counter() - start
        assert elapsed < 5.0, f"ten health checks took {elapsed:.1f}s while the bus was saturated"


class TestLiveStream:
    def test_websocket_streams_events(self, client: httpx.Client) -> None:
        websockets = pytest.importorskip("websockets.sync.client", reason="websockets required")

        ws_url = BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/ws/traffic"
        client.post("/simulation/start", json={"mode": "FAKE_SPEED", "fake_speed_value": 255.0})

        import json

        seen: set[str] = set()
        with websockets.connect(ws_url, open_timeout=10) as socket:
            deadline = time.time() + 25
            while time.time() < deadline and "ATTACK_DETECTED" not in seen:
                seen.add(json.loads(socket.recv(timeout=10))["event"])

        assert "SYSTEM_STATUS" in seen, "the client was not seeded with a status snapshot"
        assert "CAN_MESSAGE" in seen, "no traffic was streamed"
        assert "ATTACK_DETECTED" in seen, "no attack was broadcast"
