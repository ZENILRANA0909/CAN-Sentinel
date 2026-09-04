"""Simulation control endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import StateDep
from app.schemas.simulation import SimulationRequest, SimulationStatusResponse
from app.schemas.traffic import CanMessageOut, InjectFrameRequest
from app.services.pipeline import MessagePipeline

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.post(
    "/start",
    response_model=SimulationStatusResponse,
    summary="Start generating CAN traffic",
    description=(
        "Starts the traffic generator, starting the monitor first if it is not "
        "already running (the response reports this as `monitor_started`). "
        "Returns 409 if the simulation is already running."
    ),
)
async def start_simulation(
    state: StateDep, payload: SimulationRequest | None = None
) -> SimulationStatusResponse:
    profile = (payload or SimulationRequest()).apply_to(state.simulation.profile)
    result = await state.simulation.start(profile)
    return SimulationStatusResponse.model_validate(result)


@router.post(
    "/stop",
    response_model=SimulationStatusResponse,
    summary="Stop generating CAN traffic",
    description="Idempotent: stopping an already-stopped simulation succeeds.",
)
async def stop_simulation(state: StateDep) -> SimulationStatusResponse:
    return SimulationStatusResponse.model_validate(await state.simulation.stop())


@router.post(
    "/mode",
    response_model=SimulationStatusResponse,
    summary="Switch simulation mode",
    description=(
        "Changes mode live without interrupting the traffic stream. Fields left "
        "out keep their current value, so switching to FAKE_SPEED does not reset "
        "flood parameters."
    ),
)
async def set_simulation_mode(
    state: StateDep, payload: SimulationRequest
) -> SimulationStatusResponse:
    profile = payload.apply_to(state.simulation.profile)
    return SimulationStatusResponse.model_validate(await state.simulation.set_profile(profile))


@router.post(
    "/reset",
    response_model=SimulationStatusResponse,
    summary="Reset the vehicle model and live counters",
    description="Clears live statistics and returns the vehicle model to its initial state. "
    "Stored history is not deleted.",
)
async def reset_simulation(state: StateDep) -> SimulationStatusResponse:
    result = await state.simulation.reset()
    state.pipeline.clear_history()
    return SimulationStatusResponse.model_validate(result)


@router.get(
    "/status",
    response_model=SimulationStatusResponse,
    summary="Simulator state",
)
async def simulation_status(state: StateDep) -> SimulationStatusResponse:
    return SimulationStatusResponse.model_validate(state.simulation.status())


@router.post(
    "/inject",
    response_model=CanMessageOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Inject a single CAN frame",
    description=(
        "Transmits one operator-supplied frame onto the bus. The frame is fully "
        "validated first; an out-of-range identifier or an oversized payload is "
        "rejected with 422. Useful for demonstrating the identifier-anomaly "
        "detector with an arbitrary ID."
    ),
)
async def inject_frame(state: StateDep, payload: InjectFrameRequest) -> CanMessageOut:
    message = MessagePipeline.validate(
        {
            "arbitration_id": payload.can_id,
            "data": payload.data,
            "is_extended_id": payload.is_extended_id,
            "source": "INJECTED",
        }
    )
    await state.simulation.inject(message)
    return CanMessageOut.model_validate(message.to_wire())
