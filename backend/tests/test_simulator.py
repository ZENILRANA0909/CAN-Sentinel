"""Traffic simulator, vehicle model and CAN interfaces."""

from __future__ import annotations

import asyncio
import random

import pytest

from app.can.factory import create_can_interface
from app.can.interface import InterfaceState
from app.can.message import CanMessage, MessageSource
from app.can.mock import MockCanInterface
from app.can.signals import (
    ID_VEHICLE_SPEED,
    SIGNAL_CATALOG,
    decode_frame,
    decode_vehicle_speed,
    encode_engine_rpm,
    encode_vehicle_speed,
    extract_vehicle_speed,
)
from app.can.virtual import VirtualCanInterface
from app.core.config import Settings
from app.core.exceptions import CanInterfaceError, ConfigurationError, SimulationError
from app.simulation.modes import CustomFrame, SimulationMode, SimulationProfile
from app.simulation.simulator import CanTrafficSimulator
from app.simulation.vehicle import VehicleState
from tests.conftest import make_message, wait_for


# --------------------------------------------------------------------------- #
# Signal codec                                                                #
# --------------------------------------------------------------------------- #
class TestSignalCodec:
    @pytest.mark.parametrize("speed", [0.0, 1.5, 60.0, 120.0, 255.0, 400.0])
    def test_speed_round_trips(self, speed: float) -> None:
        decoded = decode_vehicle_speed(encode_vehicle_speed(speed))
        assert decoded["vehicle_speed_kmh"] == pytest.approx(speed, abs=0.01)

    def test_speed_extraction_matches_the_decoder(self) -> None:
        payload = encode_vehicle_speed(88.5)
        assert extract_vehicle_speed(ID_VEHICLE_SPEED, payload) == pytest.approx(88.5, abs=0.01)

    def test_speed_extraction_ignores_other_identifiers(self) -> None:
        assert extract_vehicle_speed(0x100, encode_vehicle_speed(88.5)) is None

    def test_speed_extraction_handles_a_short_payload(self) -> None:
        assert extract_vehicle_speed(ID_VEHICLE_SPEED, b"\x01") is None

    def test_rpm_round_trips(self) -> None:
        decoded = decode_frame(0x100, encode_engine_rpm(3500.0, load_pct=40.0, throttle_pct=25.0))
        assert decoded["engine_rpm"] == pytest.approx(3500.0, abs=0.5)
        assert decoded["engine_load_pct"] == pytest.approx(40.0, abs=0.5)

    def test_checksum_is_valid_on_encoded_frames(self) -> None:
        decoded = decode_frame(ID_VEHICLE_SPEED, encode_vehicle_speed(60.0))
        assert decoded["checksum_valid"] is True

    def test_decoding_an_unknown_identifier_returns_nothing(self) -> None:
        assert decode_frame(0x123, b"\x01\x02") == {}

    def test_decoding_a_truncated_payload_is_safe(self) -> None:
        assert decode_frame(0x100, b"") == {}

    def test_every_catalogued_frame_decodes(self) -> None:
        for can_id, spec in SIGNAL_CATALOG.items():
            assert decode_frame(can_id, bytes(spec.dlc)) != {} or spec.dlc == 0


# --------------------------------------------------------------------------- #
# Vehicle model                                                               #
# --------------------------------------------------------------------------- #
class TestVehicleModel:
    def test_state_evolves_coherently(self) -> None:
        vehicle = VehicleState()
        rng = random.Random(7)
        for _ in range(2_000):
            vehicle.advance(0.02, rng)
            assert 0.0 <= vehicle.speed_kmh <= 130.0
            assert 700.0 <= vehicle.engine_rpm <= 6_500.0
            assert 0.0 <= vehicle.throttle_pct <= 100.0
            assert vehicle.odometer_km >= 0.0

    def test_acceleration_stays_within_the_plausibility_limit(self) -> None:
        """Normal driving must never trip the Fake Speed kinematic rule."""
        vehicle = VehicleState()
        rng = random.Random(11)
        previous = vehicle.speed_kmh
        worst = 0.0
        for _ in range(5_000):
            vehicle.advance(0.02, rng)
            worst = max(worst, abs(vehicle.speed_kmh - previous) / 0.02)
            previous = vehicle.speed_kmh
        assert worst < 15.0

    def test_counter_wraps_at_four_bits(self) -> None:
        vehicle = VehicleState()
        values = [vehicle.next_counter(0x100) for _ in range(18)]
        assert values[:16] == list(range(16))
        assert values[16] == 0

    def test_zero_timestep_is_a_no_op(self) -> None:
        vehicle = VehicleState()
        before = vehicle.snapshot()
        vehicle.advance(0.0, random.Random(1))
        assert vehicle.snapshot() == before


# --------------------------------------------------------------------------- #
# Interfaces                                                                  #
# --------------------------------------------------------------------------- #
class TestInterfaces:
    async def test_virtual_interface_loops_frames_back(self) -> None:
        async with VirtualCanInterface(channel="vcan0") as interface:
            await interface.send(make_message(can_id=0x123, channel="vcan0"))
            received = await interface.receive(timeout=1.0)
        assert received is not None
        assert received.arbitration_id == 0x123

    async def test_sending_on_a_closed_interface_fails(self) -> None:
        interface = VirtualCanInterface()
        with pytest.raises(CanInterfaceError, match="closed"):
            await interface.send(make_message())

    async def test_receive_times_out_cleanly(self) -> None:
        async with VirtualCanInterface() as interface:
            assert await interface.receive(timeout=0.01) is None

    async def test_batch_receive_returns_what_is_available(self) -> None:
        async with VirtualCanInterface() as interface:
            for index in range(10):
                await interface.send(make_message(can_id=0x100 + index, channel="vcan0"))
            batch = await interface.receive_batch(100, timeout=0.5)
        assert len(batch) == 10

    async def test_queue_drops_oldest_when_full_and_counts_it(self) -> None:
        """Back-pressure must keep the monitor current, and must be visible."""
        async with VirtualCanInterface(queue_size=5) as interface:
            for index in range(10):
                await interface.send(make_message(can_id=0x100 + index, channel="vcan0"))
            assert interface.stats.dropped == 5
            batch = await interface.receive_batch(100, timeout=0.5)
        # The newest frames survived.
        assert [m.arbitration_id for m in batch] == [0x105, 0x106, 0x107, 0x108, 0x109]

    async def test_frames_are_stamped_with_the_interface_channel(self) -> None:
        async with VirtualCanInterface(channel="bus-a") as interface:
            await interface.send(make_message(channel="somewhere-else"))
            received = await interface.receive(timeout=1.0)
        assert received is not None
        assert received.channel == "bus-a"

    async def test_lifecycle_is_idempotent(self) -> None:
        interface = MockCanInterface()
        await interface.open()
        await interface.open()
        assert interface.open_calls == 1
        assert interface.state is InterfaceState.OPEN
        await interface.close()
        await interface.close()
        assert interface.state is InterfaceState.CLOSED

    async def test_open_failure_is_surfaced_and_recorded(self) -> None:
        interface = MockCanInterface()
        interface.fail_on_open = True
        with pytest.raises(CanInterfaceError):
            await interface.open()
        assert interface.state is InterfaceState.ERROR
        assert interface.stats.errors == 1

    async def test_close_drains_buffered_frames(self) -> None:
        interface = MockCanInterface()
        await interface.open()
        interface.feed(make_message(), make_message())
        assert interface.pending == 2
        await interface.close()
        assert interface.pending == 0

    def test_status_is_serialisable(self) -> None:
        import json

        json.dumps(VirtualCanInterface().status())

    def test_factory_builds_each_backend(self) -> None:
        assert isinstance(create_can_interface(Settings(can_interface="virtual")), VirtualCanInterface)
        assert isinstance(create_can_interface(Settings(can_interface="mock")), MockCanInterface)

    def test_factory_rejects_an_unknown_backend(self) -> None:
        settings = Settings()
        object.__setattr__(settings, "can_interface", "nonsense")
        with pytest.raises(ConfigurationError, match="unsupported"):
            create_can_interface(settings)


# --------------------------------------------------------------------------- #
# Simulator                                                                   #
# --------------------------------------------------------------------------- #
@pytest.fixture
async def bus():
    interface = VirtualCanInterface(channel="vcan-test", queue_size=100_000)
    await interface.open()
    try:
        yield interface
    finally:
        await interface.close()


async def collect(interface: VirtualCanInterface, seconds: float) -> list[CanMessage]:
    """Drain everything the simulator produces over a wall-clock window."""
    await asyncio.sleep(seconds)
    return await interface.receive_batch(200_000, timeout=0.2)


class TestSimulatorLifecycle:
    async def test_requires_an_open_interface(self) -> None:
        simulator = CanTrafficSimulator(VirtualCanInterface())
        with pytest.raises(SimulationError, match="not open"):
            await simulator.start()

    async def test_cannot_start_twice(self, bus: VirtualCanInterface) -> None:
        simulator = CanTrafficSimulator(bus)
        await simulator.start()
        try:
            with pytest.raises(SimulationError, match="already running"):
                await simulator.start()
        finally:
            await simulator.stop()

    async def test_stop_is_idempotent(self, bus: VirtualCanInterface) -> None:
        simulator = CanTrafficSimulator(bus)
        await simulator.stop()
        await simulator.start()
        await simulator.stop()
        await simulator.stop()
        assert simulator.is_running is False

    async def test_reset_clears_counters(self, bus: VirtualCanInterface) -> None:
        simulator = CanTrafficSimulator(bus, seed=1)
        await simulator.start()
        await asyncio.sleep(0.3)
        await simulator.stop()
        assert simulator.status()["messages_generated"] > 0
        simulator.reset()
        assert simulator.status()["messages_generated"] == 0


class TestNormalMode:
    async def test_generates_every_catalogued_frame(self, bus: VirtualCanInterface) -> None:
        simulator = CanTrafficSimulator(bus, seed=3)
        await simulator.start()
        messages = await collect(bus, 1.0)
        await simulator.stop()

        seen = {message.arbitration_id for message in messages}
        assert seen == set(SIGNAL_CATALOG)
        assert all(message.source is MessageSource.SIMULATOR for message in messages)

    async def test_rate_is_close_to_the_catalogued_periods(self, bus: VirtualCanInterface) -> None:
        expected = sum(1000.0 / spec.period_ms for spec in SIGNAL_CATALOG.values())
        simulator = CanTrafficSimulator(bus, seed=5)
        await simulator.start()
        messages = await collect(bus, 1.5)
        await simulator.stop()

        observed = len(messages) / 1.5
        # Generous tolerance: the event loop's timer granularity varies by OS.
        assert observed == pytest.approx(expected, rel=0.35)

    async def test_payloads_decode_to_sane_values(self, bus: VirtualCanInterface) -> None:
        simulator = CanTrafficSimulator(bus, seed=9)
        await simulator.start()
        messages = await collect(bus, 0.8)
        await simulator.stop()

        speeds = [
            decode_frame(m.arbitration_id, m.data)["vehicle_speed_kmh"]
            for m in messages
            if m.arbitration_id == ID_VEHICLE_SPEED
        ]
        assert speeds
        assert all(0.0 <= speed <= 130.0 for speed in speeds)


class TestAttackModes:
    async def test_fake_speed_injects_the_configured_value(self, bus: VirtualCanInterface) -> None:
        simulator = CanTrafficSimulator(
            bus,
            profile=SimulationProfile(
                mode=SimulationMode.FAKE_SPEED, fake_speed_value=255.0, fake_speed_rate=50.0
            ),
            seed=13,
        )
        await simulator.start()
        messages = await collect(bus, 1.0)
        await simulator.stop()

        injected = [m for m in messages if m.source is MessageSource.INJECTED]
        assert injected
        speeds = {decode_frame(m.arbitration_id, m.data)["vehicle_speed_kmh"] for m in injected}
        assert speeds == {255.0}
        # The genuine ECU keeps transmitting alongside the spoof.
        assert any(m.source is MessageSource.SIMULATOR and m.arbitration_id == ID_VEHICLE_SPEED
                   for m in messages)

    async def test_flood_reaches_the_requested_rate(self, bus: VirtualCanInterface) -> None:
        simulator = CanTrafficSimulator(
            bus,
            profile=SimulationProfile(mode=SimulationMode.CAN_FLOOD, flood_rate=500.0, flood_can_id=0x000),
            seed=17,
        )
        await simulator.start()
        messages = await collect(bus, 1.5)
        await simulator.stop()

        flood = [m for m in messages if m.arbitration_id == 0x000]
        assert len(flood) / 1.5 == pytest.approx(500.0, rel=0.3)

    async def test_mixed_mode_runs_both_attacks(self, bus: VirtualCanInterface) -> None:
        simulator = CanTrafficSimulator(
            bus,
            profile=SimulationProfile(
                mode=SimulationMode.MIXED, flood_rate=300.0, fake_speed_rate=50.0
            ),
            seed=19,
        )
        await simulator.start()
        messages = await collect(bus, 1.2)
        await simulator.stop()

        assert any(m.arbitration_id == 0x000 for m in messages)
        assert any(
            m.arbitration_id == ID_VEHICLE_SPEED and m.source is MessageSource.INJECTED
            for m in messages
        )

    async def test_custom_mode_emits_the_supplied_frames(self, bus: VirtualCanInterface) -> None:
        simulator = CanTrafficSimulator(
            bus,
            profile=SimulationProfile(
                mode=SimulationMode.CUSTOM,
                custom_frames=[CustomFrame(can_id=0x123, data="DEADBEEF", interval_ms=50)],
            ),
            seed=23,
        )
        await simulator.start()
        messages = await collect(bus, 1.0)
        await simulator.stop()

        custom = [m for m in messages if m.arbitration_id == 0x123]
        assert len(custom) >= 10
        assert custom[0].data_hex == "DEADBEEF"
        assert custom[0].source is MessageSource.INJECTED

    async def test_mode_can_be_switched_live(self, bus: VirtualCanInterface) -> None:
        simulator = CanTrafficSimulator(bus, seed=29)
        await simulator.start()
        await asyncio.sleep(0.3)
        await bus.receive_batch(100_000, timeout=0.1)

        await simulator.set_profile(
            SimulationProfile(mode=SimulationMode.CAN_FLOOD, flood_rate=400.0)
        )
        messages = await collect(bus, 0.8)
        await simulator.stop()

        assert simulator.mode is SimulationMode.CAN_FLOOD
        assert any(m.arbitration_id == 0x000 for m in messages)

    async def test_generated_rate_is_reported(self, bus: VirtualCanInterface) -> None:
        simulator = CanTrafficSimulator(bus, seed=31)
        await simulator.start()
        await wait_for(lambda: simulator.generated_rate > 0, timeout=3.0)
        rate = simulator.generated_rate
        await simulator.stop()
        assert rate > 0


class TestSimulationProfile:
    def test_custom_frame_payload_is_validated(self) -> None:
        assert CustomFrame(can_id=0x123, data="de ad").data == "DEAD"
        with pytest.raises(ValueError):
            CustomFrame(can_id=0x123, data="XYZ")
        with pytest.raises(ValueError, match="classic CAN limit"):
            CustomFrame(can_id=0x123, data="00" * 9)

    def test_describe_includes_the_relevant_parameters(self) -> None:
        flood = SimulationProfile(mode=SimulationMode.CAN_FLOOD, flood_rate=900.0).describe()
        assert flood["flood_rate"] == 900.0
        assert "fake_speed_value" not in flood

        spoof = SimulationProfile(mode=SimulationMode.FAKE_SPEED).describe()
        assert "fake_speed_value" in spoof
        assert "flood_rate" not in spoof

    def test_attack_modes_are_marked(self) -> None:
        assert SimulationMode.NORMAL.is_attack is False
        assert SimulationMode.FAKE_SPEED.is_attack is True
        assert SimulationMode.MIXED.is_attack is True
        assert SimulationMode.CUSTOM.is_attack is False
