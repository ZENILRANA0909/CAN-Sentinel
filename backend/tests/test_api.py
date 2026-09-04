"""REST API contract tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.version import __version__


class TestSystemEndpoints:
    async def test_health(self, client: AsyncClient) -> None:
        response = await client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert body["service"] == "can-sentinel"
        assert body["version"] == __version__
        assert body["checks"]["database"]["healthy"] is True

    async def test_version(self, client: AsyncClient) -> None:
        body = (await client.get("/api/version")).json()
        assert body == {
            "service": "can-sentinel",
            "version": __version__,
            "environment": "testing",
            "api_prefix": "/api",
        }

    async def test_status_reports_every_subsystem(self, client: AsyncClient) -> None:
        body = (await client.get("/api/status")).json()
        for section in (
            "monitor",
            "simulation",
            "detection",
            "traffic",
            "security",
            "websocket",
            "storage",
            "telemetry",
        ):
            assert section in body, section
        assert body["detection"]["detectors"]

    async def test_root_redirects_to_the_docs(self, client: AsyncClient) -> None:
        response = await client.get("/")
        assert response.status_code in (307, 308)
        assert response.headers["location"] == "/docs"

    async def test_openapi_schema_is_served(self, client: AsyncClient) -> None:
        schema = (await client.get("/openapi.json")).json()
        assert schema["info"]["version"] == __version__
        assert "/api/health" in schema["paths"]
        assert "/api/simulation/start" in schema["paths"]

    async def test_unknown_route_returns_404(self, client: AsyncClient) -> None:
        assert (await client.get("/api/nope")).status_code == 404

    async def test_system_events_are_recorded(self, client: AsyncClient) -> None:
        events = (await client.get("/api/system/events?limit=10")).json()
        assert any(event["event_type"] == "APPLICATION_STARTED" for event in events)


class TestMonitorLifecycle:
    async def test_start_stop_cycle(self, client: AsyncClient) -> None:
        assert (await client.get("/api/monitor/status")).json()["running"] is False

        started = await client.post("/api/monitor/start")
        assert started.status_code == 200
        assert started.json()["running"] is True
        assert started.json()["interface"]["is_open"] is True

        stopped = await client.post("/api/monitor/stop")
        assert stopped.status_code == 200
        assert stopped.json()["running"] is False

    async def test_starting_twice_is_a_conflict(self, client: AsyncClient) -> None:
        await client.post("/api/monitor/start")
        conflict = await client.post("/api/monitor/start")
        assert conflict.status_code == 409
        assert conflict.json()["error"] == "monitor_error"

    async def test_stopping_twice_is_allowed(self, client: AsyncClient) -> None:
        await client.post("/api/monitor/start")
        await client.post("/api/monitor/stop")
        assert (await client.post("/api/monitor/stop")).status_code == 200


class TestSimulationEndpoints:
    async def test_start_also_starts_the_monitor(self, client: AsyncClient) -> None:
        response = await client.post("/api/simulation/start", json={"mode": "NORMAL"})
        assert response.status_code == 200
        body = response.json()
        assert body["running"] is True
        assert body["mode"] == "NORMAL"
        assert body["monitor_started"] is True
        await client.post("/api/simulation/stop")

    async def test_starting_twice_is_a_conflict(self, client: AsyncClient) -> None:
        await client.post("/api/simulation/start")
        conflict = await client.post("/api/simulation/start")
        assert conflict.status_code == 409
        assert conflict.json()["error"] == "simulation_error"
        await client.post("/api/simulation/stop")

    async def test_mode_switch_preserves_unspecified_parameters(self, client: AsyncClient) -> None:
        await client.post(
            "/api/simulation/start", json={"mode": "CAN_FLOOD", "flood_rate": 700.0}
        )
        body = (await client.post("/api/simulation/mode", json={"mode": "FAKE_SPEED"})).json()
        assert body["mode"] == "FAKE_SPEED"
        assert body["previous_mode"] == "CAN_FLOOD"

        # Switching back shows the flood rate was not silently reset.
        back = (await client.post("/api/simulation/mode", json={"mode": "CAN_FLOOD"})).json()
        assert back["profile"]["flood_rate"] == 700.0
        await client.post("/api/simulation/stop")

    async def test_custom_mode_requires_frames(self, client: AsyncClient) -> None:
        response = await client.post("/api/simulation/mode", json={"mode": "CUSTOM"})
        assert response.status_code == 422
        assert response.json()["error"] == "validation_error"

    async def test_stop_is_idempotent(self, client: AsyncClient) -> None:
        assert (await client.post("/api/simulation/stop")).status_code == 200
        assert (await client.post("/api/simulation/stop")).json()["running"] is False

    async def test_reset_clears_live_counters(self, client: AsyncClient) -> None:
        await client.post("/api/simulation/start")
        body = (await client.post("/api/simulation/reset")).json()
        assert body["messages_generated"] == 0
        await client.post("/api/simulation/stop")

    async def test_status_lists_the_available_modes(self, client: AsyncClient) -> None:
        body = (await client.get("/api/simulation/status")).json()
        values = {mode["value"] for mode in body["available_modes"]}
        assert values == {"NORMAL", "FAKE_SPEED", "CAN_FLOOD", "MIXED", "CUSTOM"}

    async def test_rejects_an_out_of_range_flood_rate(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/simulation/start", json={"mode": "CAN_FLOOD", "flood_rate": 999_999}
        )
        assert response.status_code == 422


class TestFrameInjection:
    async def test_injects_a_valid_frame(self, client: AsyncClient) -> None:
        await client.post("/api/monitor/start")
        response = await client.post(
            "/api/simulation/inject", json={"can_id": 0x123, "data": "DEADBEEF"}
        )
        assert response.status_code == 202
        body = response.json()
        assert body["can_id_hex"] == "0x123"
        assert body["data"] == "DEADBEEF"
        assert body["source"] == "INJECTED"

    async def test_rejects_an_out_of_range_identifier(self, client: AsyncClient) -> None:
        await client.post("/api/monitor/start")
        response = await client.post("/api/simulation/inject", json={"can_id": 0x900, "data": "00"})
        assert response.status_code == 422
        assert response.json()["error"] == "invalid_can_message"

    async def test_rejects_an_oversized_payload(self, client: AsyncClient) -> None:
        await client.post("/api/monitor/start")
        response = await client.post(
            "/api/simulation/inject", json={"can_id": 0x123, "data": "00" * 9}
        )
        assert response.status_code == 422

    async def test_rejects_a_malformed_payload(self, client: AsyncClient) -> None:
        await client.post("/api/monitor/start")
        response = await client.post("/api/simulation/inject", json={"can_id": 0x123, "data": "XY"})
        assert response.status_code == 422

    async def test_fails_cleanly_when_the_bus_is_closed(self, client: AsyncClient) -> None:
        response = await client.post("/api/simulation/inject", json={"can_id": 0x123, "data": "00"})
        assert response.status_code == 409
        assert "not open" in response.json()["message"]


class TestTrafficEndpoints:
    async def test_recent_messages_are_empty_before_monitoring(self, client: AsyncClient) -> None:
        assert (await client.get("/api/messages/recent")).json() == []

    async def test_messages_page_shape(self, client: AsyncClient) -> None:
        body = (await client.get("/api/messages?limit=5")).json()
        assert set(body) == {"items", "total", "limit", "offset", "has_more"}

    async def test_traffic_statistics_shape(self, client: AsyncClient) -> None:
        body = (await client.get("/api/traffic/statistics")).json()
        for key in ("total_messages", "current_rate_msg_per_s", "top_can_ids", "stored_messages"):
            assert key in body

    async def test_traffic_rate_includes_the_thresholds(self, client: AsyncClient) -> None:
        body = (await client.get("/api/traffic/rate")).json()
        assert body["flood_threshold_msg_per_s"] > 0
        assert body["flood_suspicious_threshold_msg_per_s"] < body["flood_threshold_msg_per_s"]

    async def test_can_id_filter_accepts_hex_and_decimal(self, client: AsyncClient) -> None:
        assert (await client.get("/api/messages?can_id=0x300")).status_code == 200
        assert (await client.get("/api/messages?can_id=768")).status_code == 200

    async def test_rejects_a_malformed_can_id_filter(self, client: AsyncClient) -> None:
        response = await client.get("/api/messages?can_id=nonsense")
        assert response.status_code == 500 or response.json()["error"] == "internal_error"

    @pytest.mark.parametrize("limit", [0, -1, 5000])
    async def test_limit_bounds_are_enforced(self, client: AsyncClient, limit: int) -> None:
        assert (await client.get(f"/api/messages?limit={limit}")).status_code == 422


class TestSecurityEndpoints:
    async def test_recent_attacks_start_empty(self, client: AsyncClient) -> None:
        assert (await client.get("/api/attacks/recent")).json() == []

    async def test_attack_statistics_shape(self, client: AsyncClient) -> None:
        body = (await client.get("/api/attacks/statistics")).json()
        for key in ("total_events", "by_attack_type", "by_severity", "timeline", "threat_level"):
            assert key in body

    async def test_security_summary_shape(self, client: AsyncClient) -> None:
        body = (await client.get("/api/security/summary")).json()
        assert body["threat_level"] == "NORMAL"
        assert len(body["detectors"]) == 4
        assert body["monitor_running"] is False

    async def test_missing_event_returns_404(self, client: AsyncClient) -> None:
        response = await client.get("/api/attacks/999999")
        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    async def test_triage_of_a_missing_event_returns_404(self, client: AsyncClient) -> None:
        response = await client.patch("/api/attacks/999999", json={"status": "RESOLVED"})
        assert response.status_code == 404

    async def test_triage_rejects_an_invalid_status(self, client: AsyncClient) -> None:
        response = await client.patch("/api/attacks/1", json={"status": "BOGUS"})
        assert response.status_code == 422

    async def test_filters_are_validated(self, client: AsyncClient) -> None:
        assert (await client.get("/api/attacks?attack_type=FAKE_SPEED")).status_code == 200
        assert (await client.get("/api/attacks?attack_type=NOT_A_TYPE")).status_code == 422
        assert (await client.get("/api/attacks?severity=HIGH")).status_code == 200
        assert (await client.get("/api/attacks?severity=EXTREME")).status_code == 422


class TestConfigurationEndpoints:
    async def test_read_configuration(self, client: AsyncClient) -> None:
        body = (await client.get("/api/config")).json()
        assert body["revision"] >= 1
        assert body["detection"]["flood_threshold"] > 0
        assert "demonstration values" in body["defaults_note"]

    async def test_partial_update_changes_only_what_was_sent(self, client: AsyncClient) -> None:
        before = (await client.get("/api/config")).json()
        response = await client.put(
            "/api/config", json={"detection": {"fake_speed_threshold": 180.0}}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["changed"] == ["detection.fake_speed_threshold"]
        assert body["detection"]["fake_speed_threshold"] == 180.0
        assert body["detection"]["flood_threshold"] == before["detection"]["flood_threshold"]

    async def test_empty_update_is_a_no_op(self, client: AsyncClient) -> None:
        body = (await client.put("/api/config", json={})).json()
        assert body["changed"] == []

    async def test_invalid_combination_is_rejected_atomically(self, client: AsyncClient) -> None:
        before = (await client.get("/api/config")).json()
        response = await client.put(
            "/api/config",
            json={
                "detection": {
                    "fake_speed_threshold": 50.0,
                    "fake_speed_suspicious_threshold": 400.0,
                }
            },
        )
        assert response.status_code == 400
        assert response.json()["error"] == "configuration_error"

        after = (await client.get("/api/config")).json()
        assert after["detection"] == before["detection"]

    async def test_bus_changes_are_flagged_as_restart_required(self, client: AsyncClient) -> None:
        body = (await client.put("/api/config", json={"can": {"channel": "can9"}})).json()
        assert body["restart_required"] == ["can.channel"]

    async def test_unknown_field_is_rejected(self, client: AsyncClient) -> None:
        response = await client.put("/api/config", json={"detection": {"nonsense": 1}})
        assert response.status_code == 422

    async def test_reset_restores_the_environment_defaults(self, client: AsyncClient) -> None:
        original = (await client.get("/api/config")).json()["detection"]["fake_speed_threshold"]
        await client.put("/api/config", json={"detection": {"fake_speed_threshold": 111.0}})
        restored = (await client.post("/api/config/reset")).json()
        assert restored["detection"]["fake_speed_threshold"] == original

    async def test_allowlist_accepts_a_list_of_identifiers(self, client: AsyncClient) -> None:
        body = (
            await client.put("/api/config", json={"detection": {"allowed_can_ids": [0x100, 0x123]}})
        ).json()
        assert body["detection"]["allowed_can_ids"] == [0x100, 0x123]
