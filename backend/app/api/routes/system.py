"""System endpoints: health, status, version and the audit trail."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import StateDep, run_in_session
from app.core.version import SERVICE_NAME, __version__
from app.schemas.common import HealthResponse, VersionResponse
from app.schemas.system import StatusResponse, SystemEventOut
from app.storage.repositories import SystemEventRepository

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness and readiness probe",
    description=(
        "Returns `healthy` when the database responds. Used by process managers "
        "and by the dashboard to detect a backend outage."
    ),
)
async def health(state: StateDep) -> HealthResponse:
    return HealthResponse.model_validate(await state.health())


@router.get(
    "/version",
    response_model=VersionResponse,
    summary="Build identity",
)
async def version(state: StateDep) -> VersionResponse:
    return VersionResponse(
        service=SERVICE_NAME,
        version=__version__,
        environment=state.settings.app_env,
        api_prefix=state.settings.api_prefix,
    )


@router.get(
    "/status",
    response_model=StatusResponse,
    summary="Full system snapshot",
    description=(
        "Everything the System page renders: monitor, simulator, detector, "
        "traffic, security, WebSocket and storage state in one document."
    ),
)
async def status(state: StateDep) -> StatusResponse:
    return StatusResponse.model_validate(state.status())


@router.get(
    "/system/events",
    response_model=list[SystemEventOut],
    summary="Recent system audit events",
    description="Startup, shutdown, monitor and simulator transitions, and recorded errors.",
)
async def system_events(
    state: StateDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    event_type: Annotated[str | None, Query(description="Filter by event type.")] = None,
) -> list[SystemEventOut]:
    # Commit anything still buffered so the audit trail is not a step behind.
    await state.writer.flush()
    rows = await run_in_session(
        state, lambda session: SystemEventRepository(session).recent(limit, event_type=event_type)
    )
    return [SystemEventOut.model_validate(row) for row in rows]
