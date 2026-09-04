"""CAN traffic simulator.

Generates a realistic vehicle bus - and, on demand, the attacks against it -
by transmitting onto whatever :class:`~app.can.interface.BaseCanInterface` it
was given.  Nothing downstream knows the frames are synthetic: they travel the
same interface, pipeline, detector and storage path as frames from a physical
adapter.

Timing is driven by a fixed tick with per-frame due times, and attack traffic
uses a rate accumulator, so the requested frames-per-second is met accurately
without spinning the event loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from collections import deque
from typing import Any

from app.can.interface import BaseCanInterface
from app.can.message import CanDirection, CanMessage, MessageSource
from app.can.signals import (
    ID_BODY_CONTROL,
    ID_BRAKE_STATUS,
    ID_COOLANT_TEMP,
    ID_ENGINE_RPM,
    ID_STEERING,
    ID_TRANSMISSION,
    ID_VEHICLE_SPEED,
    SIGNAL_CATALOG,
    encode_brake_status,
    encode_coolant_temp,
    encode_engine_rpm,
    encode_steering,
    encode_transmission,
    encode_vehicle_speed,
)
from app.core.exceptions import CanInterfaceError, SimulationError
from app.core.logging import get_logger
from app.simulation.modes import SimulationMode, SimulationProfile
from app.simulation.vehicle import VehicleState

logger = get_logger("simulation.simulator")

#: Scheduler granularity. 5 ms is fine enough for a 10 ms frame period while
#: leaving the event loop almost entirely idle.
TICK_SECONDS = 0.005
#: Never emit more than this many attack frames in a single tick, so a stalled
#: loop cannot discharge a huge burst all at once.
MAX_BURST_MULTIPLIER = 4.0
RATE_WINDOW_SECONDS = 2.0
#: Upper bound on periodic frames emitted for one identifier in a single tick.
MAX_CATCHUP_FRAMES = 8


class CanTrafficSimulator:
    """Produces vehicle traffic and attack traffic on a CAN interface."""

    def __init__(
        self,
        interface: BaseCanInterface,
        *,
        profile: SimulationProfile | None = None,
        tick_seconds: float = TICK_SECONDS,
        max_rate: float = 5000.0,
        seed: int | None = None,
    ) -> None:
        self._interface = interface
        self._profile = profile or SimulationProfile()
        self._tick = max(0.001, tick_seconds)
        self._max_rate = max_rate
        self._rng = random.Random(seed)
        self._vehicle = VehicleState()

        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._started_at: float | None = None
        self._stopped_at: float | None = None

        self._next_due: dict[int, float] = {}
        self._custom_due: dict[int, float] = {}
        self._flood_debt = 0.0
        self._spoof_debt = 0.0

        self._emitted = 0
        self._emitted_normal = 0
        self._emitted_attack = 0
        self._errors = 0
        self._last_error: str | None = None
        self._rate_samples: deque[tuple[float, int]] = deque()

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #
    async def start(self, profile: SimulationProfile | None = None) -> None:
        """Begin generating traffic. Raises if already running."""
        if self._running:
            raise SimulationError("simulator is already running")
        if not self._interface.is_open:
            raise SimulationError(
                "cannot start the simulator: the CAN interface is not open "
                "(start the monitor first)"
            )
        if profile is not None:
            self._profile = profile
        self._running = True
        self._started_at = time.time()
        self._stopped_at = None
        self._schedule_all(time.time())
        self._task = asyncio.create_task(self._run(), name="can-sentinel-simulator")
        logger.info("Simulator started", extra={"context": self._profile.describe()})

    async def stop(self) -> None:
        """Stop generating traffic. Idempotent."""
        if not self._running:
            return
        self._running = False
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._stopped_at = time.time()
        self._flood_debt = 0.0
        self._spoof_debt = 0.0
        logger.info(
            "Simulator stopped",
            extra={"context": {"emitted": self._emitted, "errors": self._errors}},
        )

    async def set_profile(self, profile: SimulationProfile) -> SimulationProfile:
        """Switch mode/parameters without interrupting the traffic stream."""
        previous = self._profile.mode
        self._profile = profile
        self._flood_debt = 0.0
        self._spoof_debt = 0.0
        now = time.time()
        self._custom_due = {index: now for index in range(len(profile.custom_frames))}
        logger.info(
            "Simulator mode changed",
            extra={"context": {"from": previous.value, "to": profile.mode.value}},
        )
        return profile

    def reset(self) -> None:
        """Return the vehicle model and counters to their initial state."""
        self._vehicle = VehicleState()
        self._emitted = 0
        self._emitted_normal = 0
        self._emitted_attack = 0
        self._errors = 0
        self._last_error = None
        self._flood_debt = 0.0
        self._spoof_debt = 0.0
        self._rate_samples.clear()
        self._schedule_all(time.time())

    # ------------------------------------------------------------------ #
    # Main loop                                                          #
    # ------------------------------------------------------------------ #
    async def _run(self) -> None:
        last = time.time()
        while self._running:
            try:
                await asyncio.sleep(self._tick)
                now = time.time()
                dt = min(now - last, 0.25)  # clamp so a stall cannot warp the model
                last = now
                self._vehicle.advance(dt, self._rng)
                emitted = await self._emit_due(now, dt)
                if emitted:
                    self._record_rate(now, emitted)
            except asyncio.CancelledError:
                raise
            except CanInterfaceError as exc:
                self._errors += 1
                self._last_error = str(exc)
                logger.error("Simulator transmit failed", extra={"context": {"error": str(exc)}})
                await asyncio.sleep(0.25)
            except Exception as exc:  # pragma: no cover - defensive
                self._errors += 1
                self._last_error = str(exc)
                logger.error(
                    "Simulator iteration failed",
                    exc_info=True,
                    extra={"context": {"error": str(exc)}},
                )
                await asyncio.sleep(0.25)

    async def _emit_due(self, now: float, dt: float) -> int:
        profile = self._profile
        count = 0

        # --- Genuine periodic vehicle traffic ----------------------------
        # The event loop's timer granularity (~15.6 ms on Windows) is coarser
        # than the fastest frame period (10 ms), so a tick can be due several
        # frames at once. Each is emitted stamped at its scheduled time, which
        # keeps the frame's real rate correct on every platform instead of
        # silently capping it at one frame per tick.
        for can_id, due in list(self._next_due.items()):
            if now < due:
                continue
            spec = SIGNAL_CATALOG[can_id]
            period = spec.period_ms / 1000.0 / profile.traffic_scale
            emitted_for_id = 0
            while due <= now and emitted_for_id < MAX_CATCHUP_FRAMES:
                await self._transmit(self._build_periodic(can_id, due), attack=False)
                due += period
                emitted_for_id += 1
                count += 1
            # If we are still behind after the catch-up cap, give up on the
            # backlog rather than accumulating unbounded lag.
            self._next_due[can_id] = due if due > now else now + period

        # --- Attack traffic ----------------------------------------------
        if profile.mode in (SimulationMode.FAKE_SPEED, SimulationMode.MIXED):
            count += await self._emit_spoofed_speed(now, dt)
        if profile.mode in (SimulationMode.CAN_FLOOD, SimulationMode.MIXED):
            count += await self._emit_flood(now, dt)
        if profile.mode is SimulationMode.CUSTOM:
            count += await self._emit_custom(now)

        return count

    async def _emit_spoofed_speed(self, now: float, dt: float) -> int:
        profile = self._profile
        rate = min(profile.fake_speed_rate, self._max_rate)
        cap = rate * MAX_BURST_MULTIPLIER * max(self._tick, dt) + 1
        self._spoof_debt = min(self._spoof_debt + rate * dt, cap)
        emit = int(self._spoof_debt)
        if emit <= 0:
            return 0
        self._spoof_debt -= emit
        payload = encode_vehicle_speed(
            profile.fake_speed_value,
            wheel_pulses=self._vehicle.wheel_pulses,
            counter=self._vehicle.next_counter(ID_VEHICLE_SPEED),
        )
        for _ in range(emit):
            await self._transmit(
                CanMessage(
                    timestamp=time.time(),
                    arbitration_id=ID_VEHICLE_SPEED,
                    data=payload,
                    channel=self._interface.channel,
                    direction=CanDirection.RX,
                    source=MessageSource.INJECTED,
                ),
                attack=True,
            )
        return emit

    async def _emit_flood(self, now: float, dt: float) -> int:
        profile = self._profile
        rate = min(profile.flood_rate, self._max_rate)
        cap = rate * MAX_BURST_MULTIPLIER * max(self._tick, dt) + 1
        self._flood_debt = min(self._flood_debt + rate * dt, cap)
        emit = int(self._flood_debt)
        if emit <= 0:
            return 0
        self._flood_debt -= emit
        for index in range(emit):
            payload = bytes(
                [
                    0xFF,
                    (self._emitted_attack + index) & 0xFF,
                    self._rng.randrange(256),
                    0xAA,
                    0x55,
                    0xFF,
                    0x00,
                    0xFF,
                ]
            )
            await self._transmit(
                CanMessage(
                    timestamp=time.time(),
                    arbitration_id=profile.flood_can_id,
                    data=payload,
                    channel=self._interface.channel,
                    direction=CanDirection.RX,
                    source=MessageSource.INJECTED,
                ),
                attack=True,
            )
        return emit

    async def _emit_custom(self, now: float) -> int:
        count = 0
        for index, frame in enumerate(self._profile.custom_frames):
            due = self._custom_due.get(index, now)
            if now < due:
                continue
            period = frame.interval_ms / 1000.0
            nxt = due + period
            self._custom_due[index] = nxt if nxt > now else now + period
            await self._transmit(
                CanMessage(
                    timestamp=time.time(),
                    arbitration_id=frame.can_id,
                    is_extended_id=frame.is_extended_id,
                    data=frame.payload,
                    channel=self._interface.channel,
                    direction=CanDirection.RX,
                    source=MessageSource.INJECTED,
                ),
                attack=True,
            )
            count += 1
        return count

    # ------------------------------------------------------------------ #
    # Frame construction                                                 #
    # ------------------------------------------------------------------ #
    def _build_periodic(self, can_id: int, now: float) -> CanMessage:
        vehicle = self._vehicle
        if can_id == ID_ENGINE_RPM:
            payload = encode_engine_rpm(
                vehicle.engine_rpm,
                load_pct=vehicle.engine_load_pct,
                throttle_pct=vehicle.throttle_pct,
                counter=vehicle.next_counter(can_id),
            )
        elif can_id == ID_COOLANT_TEMP:
            payload = encode_coolant_temp(
                vehicle.coolant_temp_c,
                oil_c=vehicle.oil_temp_c,
                fuel_pct=vehicle.fuel_level_pct,
                ambient_c=vehicle.ambient_temp_c,
            )
        elif can_id == ID_VEHICLE_SPEED:
            payload = encode_vehicle_speed(
                vehicle.speed_kmh,
                wheel_pulses=vehicle.wheel_pulses,
                counter=vehicle.next_counter(can_id),
            )
        elif can_id == ID_BRAKE_STATUS:
            payload = encode_brake_status(
                pressed=vehicle.brake_pressed,
                abs_active=vehicle.abs_active,
                handbrake=vehicle.speed_kmh < 0.2 and vehicle.gear == 15,
                pedal_pct=vehicle.brake_pedal_pct,
                pressure_bar=vehicle.brake_pressure_bar,
            )
        elif can_id == ID_STEERING:
            payload = encode_steering(
                vehicle.steering_angle_deg,
                rate_dps=vehicle.steering_rate_dps,
                torque_nm=vehicle.steering_torque_nm,
                counter=vehicle.next_counter(can_id),
            )
        elif can_id == ID_TRANSMISSION:
            payload = encode_transmission(
                vehicle.gear,
                mode=vehicle.drive_mode,
                output_rpm=vehicle.output_shaft_rpm,
                oil_c=vehicle.oil_temp_c,
                counter=vehicle.next_counter(can_id),
            )
        elif can_id == ID_BODY_CONTROL:
            flags = 0x01 | (0x02 if vehicle.coolant_temp_c > 0 else 0)
            payload = bytes([flags, vehicle.gear & 0xFF, 0x00, vehicle.next_counter(can_id)])
        else:  # pragma: no cover - catalog and builder are kept in sync
            payload = bytes(SIGNAL_CATALOG[can_id].dlc)
        return CanMessage(
            timestamp=now,
            arbitration_id=can_id,
            data=payload,
            channel=self._interface.channel,
            direction=CanDirection.RX,
            source=MessageSource.SIMULATOR,
        )

    async def _transmit(self, message: CanMessage, *, attack: bool) -> None:
        await self._interface.send(message)
        self._emitted += 1
        if attack:
            self._emitted_attack += 1
        else:
            self._emitted_normal += 1

    # ------------------------------------------------------------------ #
    # Scheduling / statistics                                            #
    # ------------------------------------------------------------------ #
    def _schedule_all(self, now: float) -> None:
        # Stagger the first transmission of each frame so they do not all land
        # on the same tick, which would produce an unrealistic rate spike.
        self._next_due = {
            can_id: now + (index + 1) * 0.002 for index, can_id in enumerate(SIGNAL_CATALOG)
        }
        self._custom_due = {index: now for index in range(len(self._profile.custom_frames))}

    def _record_rate(self, now: float, count: int) -> None:
        self._rate_samples.append((now, count))
        cutoff = now - RATE_WINDOW_SECONDS
        while self._rate_samples and self._rate_samples[0][0] < cutoff:
            self._rate_samples.popleft()

    @property
    def generated_rate(self) -> float:
        """Frames per second the simulator is currently producing."""
        if not self._rate_samples:
            return 0.0
        now = time.time()
        cutoff = now - RATE_WINDOW_SECONDS
        recent = [count for stamp, count in self._rate_samples if stamp >= cutoff]
        if not recent:
            return 0.0
        span = max(now - self._rate_samples[0][0], self._tick)
        return sum(recent) / min(span, RATE_WINDOW_SECONDS)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def mode(self) -> SimulationMode:
        return self._profile.mode

    @property
    def profile(self) -> SimulationProfile:
        return self._profile

    @property
    def vehicle(self) -> VehicleState:
        return self._vehicle

    def status(self) -> dict[str, Any]:
        uptime = (time.time() - self._started_at) if (self._running and self._started_at) else 0.0
        return {
            "running": self._running,
            "mode": self._profile.mode.value,
            "mode_label": self._profile.mode.label,
            "attack_active": self._profile.mode.is_attack,
            "profile": self._profile.describe(),
            "started_at": self._started_at,
            "stopped_at": self._stopped_at,
            "uptime_seconds": round(uptime, 2),
            "generated_rate_msg_per_s": round(self.generated_rate, 1),
            "messages_generated": self._emitted,
            "normal_messages": self._emitted_normal,
            "attack_messages": self._emitted_attack,
            "errors": self._errors,
            "last_error": self._last_error,
            "vehicle": self._vehicle.snapshot(),
        }
