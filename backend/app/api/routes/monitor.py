"""Monitor lifecycle endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import StateDep
from app.schemas.system import MonitorStatusResponse

router = APIRouter(prefix="/monitor", tags=["monitor"])


@router.post(
    "/start",
    response_model=MonitorStatusResponse,
    summary="Start monitoring the CAN bus",
    description=(
        "Opens the configured CAN interface and starts the receive loop. "
        "Returns 409 if already running, or 503 if the interface cannot be "
        "opened (for example, no adapter present in `python-can` mode)."
    ),
)
async def start_monitor(state: StateDep) -> MonitorStatusResponse:
    return MonitorStatusResponse.model_validate(await state.monitor.start())


@router.post(
    "/stop",
    response_model=MonitorStatusResponse,
    summary="Stop monitoring",
    description=(
        "Stops the receive loop and closes the interface. The simulator is "
        "stopped first, since it has nowhere to transmit once the bus is closed. "
        "Idempotent."
    ),
)
async def stop_monitor(state: StateDep) -> MonitorStatusResponse:
    if state.simulation.is_running:
        await state.simulation.stop()
    return MonitorStatusResponse.model_validate(await state.monitor.stop())


@router.get(
    "/status",
    response_model=MonitorStatusResponse,
    summary="Monitoring service state",
)
async def monitor_status(state: StateDep) -> MonitorStatusResponse:
    return MonitorStatusResponse.model_validate(state.monitor.status())
