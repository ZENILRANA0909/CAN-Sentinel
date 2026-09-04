"""A small vehicle model driving the simulated bus.

The point of the model is that the *values* on the bus are coherent: engine RPM
follows road speed through a gear ratio, the brake light comes on while the car
is slowing, coolant temperature warms up and then holds.  Detectors that look at
rates of change need traffic that behaves like a vehicle, not random bytes.

All rates of change here stay comfortably inside the plausibility limits used
by the Fake Speed detector, so normal driving never raises an alert.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

IDLE_RPM = 780.0
MAX_SPEED_KMH = 118.0
#: km/h per second. Well below the detector's default 15 km/h/s plausibility
#: limit, so a normal drive cycle produces no kinematic alerts.
ACCEL_RATE = 3.2
BRAKE_RATE = 5.5
COAST_RATE = 0.9

#: Upper road speed for each gear, used to pick a ratio.
GEAR_SPEEDS = ((1, 22.0), (2, 42.0), (3, 65.0), (4, 90.0), (5, 115.0), (6, 200.0))


class DrivePhase(str, Enum):
    """Coarse state of the drive cycle."""

    IDLE = "IDLE"
    ACCELERATING = "ACCELERATING"
    CRUISING = "CRUISING"
    BRAKING = "BRAKING"


@dataclass
class VehicleState:
    """Mutable physical state of the simulated vehicle."""

    speed_kmh: float = 0.0
    engine_rpm: float = IDLE_RPM
    coolant_temp_c: float = 24.0
    oil_temp_c: float = 24.0
    fuel_level_pct: float = 78.0
    ambient_temp_c: float = 21.0
    throttle_pct: float = 0.0
    engine_load_pct: float = 8.0
    brake_pressed: bool = False
    brake_pedal_pct: float = 0.0
    brake_pressure_bar: float = 0.0
    abs_active: bool = False
    steering_angle_deg: float = 0.0
    steering_rate_dps: float = 0.0
    steering_torque_nm: float = 0.0
    gear: int = 0
    drive_mode: int = 1
    output_shaft_rpm: float = 0.0
    wheel_pulses: int = 0
    odometer_km: float = 0.0

    phase: DrivePhase = DrivePhase.IDLE
    _phase_remaining: float = 4.0
    _target_speed: float = 0.0
    _elapsed: float = 0.0
    _steer_phase: float = 0.0
    counters: dict[int, int] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    def next_counter(self, can_id: int) -> int:
        """Rolling 4-bit message counter, as most production ECUs emit."""
        value = (self.counters.get(can_id, -1) + 1) & 0x0F
        self.counters[can_id] = value
        return value

    def advance(self, dt: float, rng: random.Random) -> None:
        """Advance the model by ``dt`` seconds."""
        if dt <= 0:
            return
        self._elapsed += dt
        self._phase_remaining -= dt
        if self._phase_remaining <= 0:
            self._choose_next_phase(rng)

        self._update_speed(dt, rng)
        self._update_powertrain(dt, rng)
        self._update_brakes(dt)
        self._update_steering(dt, rng)
        self._update_thermal(dt)

        distance_km = self.speed_kmh * dt / 3600.0
        self.odometer_km += distance_km
        # ~600 pulses per wheel revolution at ~2 m rolling circumference.
        self.wheel_pulses = (self.wheel_pulses + int(distance_km * 1000 * 300)) & 0xFFFF

    # ------------------------------------------------------------------ #
    def _choose_next_phase(self, rng: random.Random) -> None:
        if self.phase in (DrivePhase.IDLE, DrivePhase.BRAKING) and self.speed_kmh < 2.0:
            self.phase = DrivePhase.ACCELERATING
            self._target_speed = rng.uniform(35.0, MAX_SPEED_KMH)
            self._phase_remaining = rng.uniform(8.0, 18.0)
        elif self.phase is DrivePhase.ACCELERATING:
            self.phase = DrivePhase.CRUISING
            self._phase_remaining = rng.uniform(10.0, 25.0)
        elif self.phase is DrivePhase.CRUISING:
            if rng.random() < 0.45:
                self.phase = DrivePhase.BRAKING
                self._target_speed = rng.uniform(0.0, max(0.0, self.speed_kmh - 25.0))
                self._phase_remaining = rng.uniform(5.0, 12.0)
            else:
                self.phase = DrivePhase.ACCELERATING
                self._target_speed = rng.uniform(self.speed_kmh, MAX_SPEED_KMH)
                self._phase_remaining = rng.uniform(6.0, 14.0)
        else:
            self.phase = DrivePhase.IDLE if self.speed_kmh < 2.0 else DrivePhase.CRUISING
            self._phase_remaining = rng.uniform(4.0, 10.0)

    def _update_speed(self, dt: float, rng: random.Random) -> None:
        jitter = rng.uniform(-0.05, 0.05)
        if self.phase is DrivePhase.ACCELERATING:
            self.speed_kmh = min(self._target_speed, self.speed_kmh + ACCEL_RATE * dt)
            self.throttle_pct = min(85.0, 25.0 + self.speed_kmh * 0.35)
        elif self.phase is DrivePhase.BRAKING:
            self.speed_kmh = max(self._target_speed, self.speed_kmh - BRAKE_RATE * dt)
            self.throttle_pct = 0.0
        elif self.phase is DrivePhase.CRUISING:
            self.speed_kmh = max(0.0, self.speed_kmh + jitter)
            self.throttle_pct = max(6.0, 12.0 + self.speed_kmh * 0.16)
        else:
            self.speed_kmh = max(0.0, self.speed_kmh - COAST_RATE * dt)
            self.throttle_pct = 0.0
        self.speed_kmh = max(0.0, min(MAX_SPEED_KMH + 4.0, self.speed_kmh))

    def _update_powertrain(self, dt: float, rng: random.Random) -> None:
        self.gear = self._select_gear()
        if self.speed_kmh < 1.0:
            target_rpm = IDLE_RPM + rng.uniform(-25.0, 25.0)
        else:
            span_low, span_high = self._gear_span()
            fraction = (self.speed_kmh - span_low) / max(span_high - span_low, 1.0)
            target_rpm = 1150.0 + fraction * 3400.0 + self.throttle_pct * 4.0
        # First-order lag so RPM does not step instantaneously.
        self.engine_rpm += (target_rpm - self.engine_rpm) * min(1.0, dt * 4.0)
        self.engine_rpm = max(IDLE_RPM * 0.9, min(6500.0, self.engine_rpm))
        self.engine_load_pct = max(4.0, min(100.0, self.throttle_pct * 0.9 + 6.0))
        self.output_shaft_rpm = self.speed_kmh * 32.0

    def _select_gear(self) -> int:
        if self.speed_kmh < 1.0:
            return 15 if self.phase is DrivePhase.IDLE else 0
        for gear, ceiling in GEAR_SPEEDS:
            if self.speed_kmh <= ceiling:
                return gear
        return 6

    def _gear_span(self) -> tuple[float, float]:
        low = 0.0
        for _, ceiling in GEAR_SPEEDS:
            if self.speed_kmh <= ceiling:
                return low, ceiling
            low = ceiling
        return low, MAX_SPEED_KMH

    def _update_brakes(self, dt: float) -> None:
        if self.phase is DrivePhase.BRAKING:
            self.brake_pressed = True
            self.brake_pedal_pct = min(70.0, self.brake_pedal_pct + 90.0 * dt)
        else:
            self.brake_pressed = False
            self.brake_pedal_pct = max(0.0, self.brake_pedal_pct - 120.0 * dt)
        self.brake_pressure_bar = self.brake_pedal_pct * 1.4
        self.abs_active = self.brake_pressed and self.brake_pedal_pct > 62.0

    def _update_steering(self, dt: float, rng: random.Random) -> None:
        self._steer_phase += dt * 0.35
        previous = self.steering_angle_deg
        amplitude = 3.0 + min(18.0, self.speed_kmh * 0.12)
        self.steering_angle_deg = (
            math.sin(self._steer_phase) * amplitude + rng.uniform(-0.4, 0.4)
        )
        self.steering_rate_dps = (self.steering_angle_deg - previous) / max(dt, 1e-3)
        self.steering_torque_nm = max(-40.0, min(40.0, self.steering_rate_dps * 0.25))

    def _update_thermal(self, dt: float) -> None:
        target = 92.0 if self.speed_kmh > 0.5 else 88.0
        self.coolant_temp_c += (target - self.coolant_temp_c) * min(1.0, dt * 0.02)
        self.oil_temp_c += (self.coolant_temp_c + 6.0 - self.oil_temp_c) * min(1.0, dt * 0.015)
        # Roughly 6 L/100 km; slow enough that the gauge visibly moves over a demo.
        self.fuel_level_pct = max(0.0, self.fuel_level_pct - self.speed_kmh * dt * 1.2e-4)

    # ------------------------------------------------------------------ #
    def snapshot(self) -> dict[str, Any]:
        """Current physical state, surfaced on the Simulator page."""
        return {
            "phase": self.phase.value,
            "speed_kmh": round(self.speed_kmh, 1),
            "engine_rpm": round(self.engine_rpm),
            "gear": self.gear,
            "throttle_pct": round(self.throttle_pct, 1),
            "brake_pressed": self.brake_pressed,
            "brake_pedal_pct": round(self.brake_pedal_pct, 1),
            "coolant_temp_c": round(self.coolant_temp_c, 1),
            "fuel_level_pct": round(self.fuel_level_pct, 1),
            "steering_angle_deg": round(self.steering_angle_deg, 1),
            "odometer_km": round(self.odometer_km, 3),
        }
