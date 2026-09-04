"""Simulation service: lifecycle and control surface for the traffic generator."""

from __future__ import annotations

import time
from typing import Any

from app.can.message import CanMessage
from app.core.exceptions import SimulationError
from app.core.logging import get_logger
from app.services.broadcaster import Broadcaster, EventType
from app.services.monitor import MonitorService
from app.services.statistics import TrafficStatistics
from app.simulation.modes import SimulationMode, SimulationProfile
from app.simulation.simulator import CanTrafficSimulator
from app.storage.writer import PersistenceWriter

logger = get_logger("services.simulation")


class SimulationService:
    """Starts, stops and reconfigures the CAN traffic simulator.

    The simulator transmits onto whatever interface the monitor currently has
    open, so a fresh generator is built at each start; that keeps the two in
    step when the bus configuration changes between runs.
    """

    def __init__(
        self,
        *,
        monitor: MonitorService,
        broadcaster: Broadcaster,
        writer: PersistenceWriter,
        statistics: TrafficStatistics,
        default_profile: SimulationProfile | None = None,
        max_rate: float = 5000.0,
        seed: int | None = None,
    ) -> None:
        self._monitor = monitor
        self._broadcaster = broadcaster
        self._writer = writer
        self._statistics = statistics
        self._profile = default_profile or SimulationProfile()
        self._max_rate = max_rate
        self._seed = seed
        self._simulator: CanTrafficSimulator | None = None
        self._last_started: float | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #
    async def start(self, profile: SimulationProfile | None = None) -> dict[str, Any]:
        """Start generating traffic, starting the monitor first if needed."""
        if self.is_running:
            raise SimulationError("simulation is already running")

        monitor_started = False
        if not self._monitor.is_running:
            # Without an open bus there is nowhere to transmit. Starting the
            # monitor here removes a demo footgun; the response says we did it.
            await self._monitor.start()
            monitor_started = True

        interface = self._monitor.interface
        if interface is None:  # pragma: no cover - monitor.start guarantees this
            raise SimulationError("no CAN interface is available")

        if profile is not None:
            self._profile = profile

        simulator = CanTrafficSimulator(
            interface, profile=self._profile, max_rate=self._max_rate, seed=self._seed
        )
        await simulator.start()
        self._simulator = simulator
        self._last_started = time.time()

        payload = self.status()
        payload["monitor_started"] = monitor_started
        self._writer.submit_system_event(
            event_type="SIMULATION_STARTED",
            message=f"Simulation started in {self._profile.mode.value} mode",
            context=self._profile.describe(),
        )
        self._broadcaster.publish(EventType.SIMULATION_STATUS, payload)
        return payload

    async def stop(self) -> dict[str, Any]:
        """Stop generating traffic. Idempotent."""
        if self._simulator is not None:
            await self._simulator.stop()
        payload = self.status()
        self._writer.submit_system_event(
            event_type="SIMULATION_STOPPED", message="Simulation stopped"
        )
        self._broadcaster.publish(EventType.SIMULATION_STATUS, payload)
        return payload

    async def set_profile(self, profile: SimulationProfile) -> dict[str, Any]:
        """Switch mode or parameters, live if the simulator is running."""
        previous = self._profile.mode
        self._profile = profile
        if self._simulator is not None and self._simulator.is_running:
            await self._simulator.set_profile(profile)
        payload = self.status()
        payload["previous_mode"] = previous.value
        self._writer.submit_system_event(
            event_type="SIMULATION_MODE_CHANGED",
            message=f"Simulation mode changed from {previous.value} to {profile.mode.value}",
            severity="MEDIUM" if profile.mode.is_attack else "INFO",
            context=profile.describe(),
        )
        self._broadcaster.publish(EventType.SIMULATION_STATUS, payload)
        logger.info(
            "Simulation profile applied",
            extra={"context": {"mode": profile.mode.value, "running": self.is_running}},
        )
        return payload

    async def reset(self) -> dict[str, Any]:
        """Return the vehicle model, counters and live statistics to zero."""
        if self._simulator is not None:
            self._simulator.reset()
        self._statistics.reset()
        payload = self.status()
        self._writer.submit_system_event(
            event_type="SIMULATION_RESET", message="Simulation counters reset"
        )
        self._broadcaster.publish(EventType.SIMULATION_STATUS, payload)
        return payload

    async def inject(self, message: CanMessage) -> dict[str, Any]:
        """Transmit a single operator-supplied frame onto the bus."""
        interface = self._monitor.interface
        if interface is None or not interface.is_open:
            raise SimulationError(
                "cannot inject a frame: the CAN interface is not open (start the monitor first)"
            )
        await interface.send(message)
        self._writer.submit_system_event(
            event_type="FRAME_INJECTED",
            message=f"Frame {message.can_id_hex} injected",
            context={"can_id": message.can_id_hex, "data": message.data_hex},
        )
        logger.info(
            "Frame injected",
            extra={"context": {"can_id": message.can_id_hex, "data": message.data_hex}},
        )
        return message.to_wire()

    # ------------------------------------------------------------------ #
    # Introspection                                                      #
    # ------------------------------------------------------------------ #
    @property
    def is_running(self) -> bool:
        return self._simulator is not None and self._simulator.is_running

    @property
    def mode(self) -> SimulationMode:
        return self._profile.mode

    @property
    def profile(self) -> SimulationProfile:
        return self._profile

    def status(self) -> dict[str, Any]:
        if self._simulator is not None:
            payload = self._simulator.status()
        else:
            payload = {
                "running": False,
                "mode": self._profile.mode.value,
                "mode_label": self._profile.mode.label,
                "attack_active": False,
                "profile": self._profile.describe(),
                "started_at": None,
                "stopped_at": None,
                "uptime_seconds": 0.0,
                "generated_rate_msg_per_s": 0.0,
                "messages_generated": 0,
                "normal_messages": 0,
                "attack_messages": 0,
                "errors": 0,
                "last_error": None,
                "vehicle": None,
            }
        payload["available_modes"] = [
            {"value": mode.value, "label": mode.label, "is_attack": mode.is_attack}
            for mode in SimulationMode
        ]
        payload["last_started"] = self._last_started
        return payload
