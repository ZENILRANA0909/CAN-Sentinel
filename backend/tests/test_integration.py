"""End-to-end integration.

These exercise the real data flow with nothing stubbed:

``simulator -> CAN interface -> receiver -> pipeline -> detectors -> database -> API``

They are the tests that would catch a component being wired up incorrectly even
though each part passes its own unit tests.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from app.can.message import MessageSource
from app.services.state import ApplicationState
from app.storage.repositories import CanMessageRepository
from tests.conftest import make_message, wait_for

pytestmark = pytest.mark.integration


async def stats_of(client: AsyncClient) -> dict:
    return (await client.get("/api/status")).json()


async def poll_until(check, *, timeout: float = 15.0, interval: float = 0.1) -> bool:
    """Await ``check()`` repeatedly until it is truthy or the timeout expires."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await check():
            return True
        await asyncio.sleep(interval)
    return False


async def attack_seen(client: AsyncClient, attack_type: str, *, limit: int = 50) -> bool:
    events = (await client.get(f"/api/attacks/recent?limit={limit}")).json()
    return any(event["attack_type"] == attack_type for event in events)


class TestNormalTrafficFlow:
    async def test_frames_reach_every_stage(self, client: AsyncClient) -> None:
        await client.post("/api/simulation/start", json={"mode": "NORMAL"})
        try:
            await asyncio.sleep(1.5)

            status = await stats_of(client)
            assert status["monitor"]["running"] is True
            assert status["traffic"]["total_messages"] > 50
            assert status["traffic"]["current_rate_msg_per_s"] > 0
            assert status["detection"]["analysed_messages"] > 50

            live = (await client.get("/api/messages/recent?limit=20")).json()
            assert len(live) == 20
            assert all(frame["source"] == "SIMULATOR" for frame in live)
            # Frames arrive decoded into engineering units.
            speed_frames = [f for f in live if f["can_id_hex"] == "0x300"]
            if speed_frames:
                assert "vehicle_speed_kmh" in speed_frames[0]["decoded"]

            stored = (await client.get("/api/messages?limit=5")).json()
            assert stored["total"] > 0
        finally:
            await client.post("/api/simulation/stop")

    async def test_normal_traffic_raises_no_alerts(self, client: AsyncClient) -> None:
        """The default thresholds must not fire on the simulator's normal bus."""
        await client.post("/api/simulation/start", json={"mode": "NORMAL"})
        try:
            await asyncio.sleep(3.0)
            summary = (await client.get("/api/security/summary")).json()
            assert summary["attacks_total"] == 0
            assert summary["threat_level"] == "NORMAL"
            assert summary["active_alerts"] == 0
        finally:
            await client.post("/api/simulation/stop")


class TestFakeSpeedScenario:
    async def test_detected_stored_and_served(self, client: AsyncClient) -> None:
        await client.post("/api/simulation/start", json={"mode": "NORMAL"})
        try:
            await asyncio.sleep(1.0)
            await client.post(
                "/api/simulation/mode",
                json={"mode": "FAKE_SPEED", "fake_speed_value": 255.0, "fake_speed_rate": 100.0},
            )

            assert await poll_until(
                lambda: attack_seen(client, "FAKE_SPEED")
            ), "the fake speed attack was never detected"

            events = (await client.get("/api/attacks/recent?limit=20")).json()
            spoof = next(e for e in events if e["attack_type"] == "FAKE_SPEED")

            # 1. Classified correctly.
            assert spoof["threat_level"] == "ATTACK"
            assert spoof["severity"] in {"HIGH", "CRITICAL"}
            assert spoof["can_id_hex"] == "0x300"
            assert spoof["confidence"] > 0.5

            # 2. Evidence explains the verdict.
            assert spoof["evidence"]["observed_speed_kmh"] == pytest.approx(255.0, abs=0.1)
            assert spoof["evidence"]["attack_threshold_kmh"] == 200.0

            # 3. Persisted with an identity usable for triage.
            assert spoof["id"] is not None
            triaged = await client.patch(f"/api/attacks/{spoof['id']}", json={"status": "ACKNOWLEDGED"})
            assert triaged.status_code == 200
            assert triaged.json()["status"] == "ACKNOWLEDGED"

            # 4. Reflected in the aggregates.
            summary = (await client.get("/api/security/summary")).json()
            assert summary["threat_level"] == "ATTACK"
            assert summary["by_attack_type"]["FAKE_SPEED"] >= 1
        finally:
            await client.post("/api/simulation/stop")

    async def test_spoofing_also_trips_the_frequency_detector(self, client: AsyncClient) -> None:
        """Injecting alongside the genuine ECU doubles the identifier's rate,
        which is exactly what the frequency detector exists to notice."""
        await client.post(
            "/api/simulation/start",
            json={"mode": "FAKE_SPEED", "fake_speed_value": 255.0, "fake_speed_rate": 200.0},
        )
        try:
            assert await poll_until(
                lambda: attack_seen(client, "FREQUENCY_ANOMALY")
            ), "the frequency anomaly was never reported"
        finally:
            await client.post("/api/simulation/stop")


class TestFloodScenario:
    async def test_flood_is_detected_and_bounded(self, client: AsyncClient) -> None:
        # The shared fixture runs with the cooldown disabled so unit tests see
        # every verdict; throttling is the behaviour under test here, so this
        # test asks for a realistic cooldown explicitly.
        await client.put("/api/config", json={"detection": {"event_cooldown_seconds": 2.0}})
        await client.post(
            "/api/simulation/start", json={"mode": "CAN_FLOOD", "flood_rate": 1500.0}
        )
        try:
            # A flood trips two distinct rules: the per-identifier rule fires
            # first (0x000 crosses its own threshold before the bus total
            # crosses the global one), then bus saturation. Assert on the
            # bus-saturation rule specifically, so the numbers being compared
            # are the ones that rule actually uses.
            def is_bus_saturation(event: dict) -> bool:
                return (
                    event["attack_type"] == "CAN_FLOOD"
                    and event["threat_level"] == "ATTACK"
                    and event["evidence"].get("rule") == "global_rate_above_threshold"
                )

            async def flood_attack_reported() -> bool:
                events = (await client.get("/api/attacks/recent?limit=50")).json()
                return any(is_bus_saturation(e) for e in events)

            assert await poll_until(flood_attack_reported), "the flood was never detected"

            events = (await client.get("/api/attacks/recent?limit=50")).json()
            flood = next(e for e in events if is_bus_saturation(e))
            assert flood["severity"] in {"HIGH", "CRITICAL"}
            assert flood["evidence"]["observed_rate_msg_per_s"] > flood["evidence"]["threshold_msg_per_s"]

            # The targeted-flood rule fires too, on the injector's identifier.
            targeted = [
                e for e in events
                if e["evidence"].get("rule") == "per_id_rate_above_threshold"
            ]
            if targeted:
                evidence = targeted[0]["evidence"]
                assert evidence["can_id_rate_msg_per_s"] > evidence["per_id_threshold_msg_per_s"]

            status = await stats_of(client)
            threshold = (await client.get("/api/config")).json()["detection"]["flood_threshold"]
            assert status["traffic"]["current_rate_msg_per_s"] > threshold

            # The throttler must keep a 1500 msg/s flood from writing a row per
            # frame: far more verdicts are suppressed than emitted.
            detection = status["detection"]
            assert detection["events_suppressed"] > detection["events_emitted"]
        finally:
            await client.post("/api/simulation/stop")

    async def test_flood_identifier_also_trips_the_allowlist(self, client: AsyncClient) -> None:
        await client.post("/api/simulation/start", json={"mode": "CAN_FLOOD", "flood_rate": 900.0})
        try:
            assert await poll_until(
                lambda: attack_seen(client, "ID_ANOMALY")
            ), "the unauthorised flood identifier was never reported"
        finally:
            await client.post("/api/simulation/stop")

    async def test_nothing_is_dropped_under_flood(self, client: AsyncClient) -> None:
        """The monitor must keep up with a saturated bus without losing frames.

        This asserts *correctness* under load, not latency: the ASGI transport
        runs the app on the same event loop as this test, so a wall-clock
        latency measurement here would be measuring the harness starving itself.
        Latency is measured against a real server instead - see
        ``docs/testing.md``.
        """
        await client.put("/api/config", json={"detection": {"event_cooldown_seconds": 2.0}})
        await client.post(
            "/api/simulation/start", json={"mode": "CAN_FLOOD", "flood_rate": 2000.0}
        )
        try:
            await asyncio.sleep(3.0)

            for _ in range(5):
                response = await client.get("/api/health")
                assert response.status_code == 200
                assert response.json()["status"] == "healthy"

            status = await stats_of(client)
            interface = status["monitor"]["interface"]["statistics"]
            writer = status["storage"]["writer"]

            assert interface["dropped"] == 0, "the interface queue overflowed"
            assert writer["messages_dropped"] == 0, "the persistence queue overflowed"
            assert writer["errors"] == 0
            assert status["monitor"]["errors"] == 0

            # Every frame the interface received reached the detection engine.
            assert status["detection"]["analysed_messages"] == interface["received"]
        finally:
            await client.post("/api/simulation/stop")


class TestIdAnomalyScenario:
    async def test_injected_frame_is_reported(self, client: AsyncClient) -> None:
        await client.post("/api/monitor/start")
        for _ in range(6):
            await client.post("/api/simulation/inject", json={"can_id": 0x123, "data": "DEADBEEF"})
            await asyncio.sleep(0.05)

        async def injected_id_reported() -> bool:
            events = (await client.get("/api/attacks/recent?limit=20")).json()
            return any(
                e["attack_type"] == "ID_ANOMALY" and e["can_id"] == 0x123 for e in events
            )

        assert await poll_until(injected_id_reported), "the injected identifier was never reported"

        events = (await client.get("/api/attacks/recent?limit=20")).json()
        match = next(e for e in events if e["attack_type"] == "ID_ANOMALY" and e["can_id"] == 0x123)
        assert match["evidence"]["can_id"] == "0x123"


class TestRecoveryScenario:
    async def test_full_attack_and_recovery_cycle(self, client: AsyncClient) -> None:
        await client.post("/api/simulation/start", json={"mode": "NORMAL"})
        try:
            await asyncio.sleep(1.5)
            assert (await client.get("/api/security/summary")).json()["threat_level"] == "NORMAL"

            await client.post(
                "/api/simulation/mode", json={"mode": "CAN_FLOOD", "flood_rate": 1500.0}
            )
            async def under_attack() -> bool:
                summary = (await client.get("/api/security/summary")).json()
                return summary["threat_level"] == "ATTACK"

            assert await poll_until(under_attack), "the flood never raised the threat level"

            await client.post("/api/simulation/mode", json={"mode": "NORMAL"})
            await asyncio.sleep(2.0)

            # The detector itself recovers immediately once the rate drops; the
            # dashboard's posture clears after the active-alert window.
            status = await stats_of(client)
            flood_state = next(
                d for d in status["detection"]["detectors"] if d["name"] == "can_flood"
            )["state"]
            assert flood_state["current_rate_msg_per_s"] < 600
            assert status["traffic"]["current_rate_msg_per_s"] < 600
        finally:
            await client.post("/api/simulation/stop")


class TestPipelineIntegrity:
    async def test_every_frame_is_analysed_and_persisted(self, app_state: ApplicationState) -> None:
        """No frame may be silently dropped between the bus and the database."""
        await app_state.monitor.start()
        interface = app_state.monitor.interface
        assert interface is not None

        sent = 40
        for index in range(sent):
            await interface.send(make_message(can_id=0x100, timestamp=1000.0 + index * 0.02))

        assert await wait_for(
            lambda: app_state.statistics.total_messages >= sent, timeout=5.0
        ), "the pipeline did not process every frame"

        await app_state.writer.flush()
        with app_state.database.session() as session:
            assert CanMessageRepository(session).count() == sent

        assert app_state.engine.snapshot()["analysed_messages"] == sent
        await app_state.monitor.stop()

    async def test_stopping_the_monitor_stops_the_simulator(
        self, client: AsyncClient
    ) -> None:
        await client.post("/api/simulation/start", json={"mode": "NORMAL"})
        await asyncio.sleep(0.5)
        await client.post("/api/monitor/stop")
        assert (await client.get("/api/simulation/status")).json()["running"] is False

    async def test_persistence_can_be_disabled_without_losing_events(
        self, client: AsyncClient
    ) -> None:
        """Under sustained load an operator may stop recording raw traffic;
        security events must still be stored."""
        await client.put("/api/config", json={"retention": {"persist_can_messages": False}})
        await client.post(
            "/api/simulation/start", json={"mode": "FAKE_SPEED", "fake_speed_value": 255.0}
        )
        try:
            async def any_event() -> bool:
                return bool((await client.get("/api/attacks/recent?limit=5")).json())

            assert await poll_until(any_event), "no security event was stored"
            assert (await client.get("/api/messages?limit=1")).json()["total"] == 0
        finally:
            await client.post("/api/simulation/stop")

    async def test_injected_frames_are_attributed_correctly(
        self, app_state: ApplicationState
    ) -> None:
        await app_state.monitor.start()
        interface = app_state.monitor.interface
        assert interface is not None
        await interface.send(
            make_message(can_id=0x123, source=MessageSource.INJECTED, timestamp=1000.0)
        )
        assert await wait_for(lambda: app_state.statistics.total_messages >= 1, timeout=5.0)

        await app_state.writer.flush()
        with app_state.database.session() as session:
            rows = CanMessageRepository(session).recent(1)
        assert rows[0]["source"] == "INJECTED"
        await app_state.monitor.stop()


class TestConfigurationTakesEffectLive:
    async def test_lowering_a_threshold_starts_detecting(self, client: AsyncClient) -> None:
        await client.post("/api/simulation/start", json={"mode": "NORMAL"})
        try:
            await asyncio.sleep(2.0)
            assert (await client.get("/api/security/summary")).json()["attacks_total"] == 0

            # Drop the flood threshold below the simulator's normal bus load.
            await client.put(
                "/api/config",
                json={"detection": {"flood_threshold": 50.0, "per_id_flood_threshold": 50.0}},
            )

            assert await poll_until(
                lambda: attack_seen(client, "CAN_FLOOD", limit=10)
            ), "the retuned threshold did not take effect on live traffic"
        finally:
            await client.post("/api/simulation/stop")
