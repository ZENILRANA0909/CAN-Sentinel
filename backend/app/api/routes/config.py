"""Runtime configuration endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import StateDep
from app.core.runtime_config import ConfigService
from app.schemas.system import ConfigResponse, ConfigUpdateRequest

router = APIRouter(prefix="/config", tags=["configuration"])


def _response(state: StateDep, changed: list[str] | None = None) -> ConfigResponse:
    config = state.config_service.current
    changed = changed or []
    return ConfigResponse(
        revision=state.config_service.revision,
        detection=config.detection,
        can=config.can,
        retention=config.retention,
        changed=changed,
        restart_required=ConfigService.restart_required(changed),
    )


@router.get(
    "",
    response_model=ConfigResponse,
    summary="Read the runtime configuration",
    description=(
        "Detection thresholds, bus parameters and retention limits currently in "
        "force. Detection thresholds are demonstration values, not vehicle "
        "safety limits."
    ),
)
async def get_config(state: StateDep) -> ConfigResponse:
    return _response(state)


@router.put(
    "",
    response_model=ConfigResponse,
    summary="Update the runtime configuration",
    description=(
        "Partial update: only the sections and fields supplied are changed. "
        "Detection changes take effect on the very next frame. Bus changes "
        "(channel, bitrate, interface) apply the next time the monitor starts "
        "and are listed in `restart_required`. An invalid combination is "
        "rejected with 400 and nothing is applied."
    ),
)
async def update_config(state: StateDep, payload: ConfigUpdateRequest) -> ConfigResponse:
    patch = payload.to_patch()
    if not patch:
        return _response(state)
    _, changed = state.config_service.update(patch)
    if changed:
        state.writer.submit_system_event(
            event_type="CONFIG_UPDATED",
            message=f"Configuration updated: {', '.join(changed)}",
            context={"changed": changed, "revision": state.config_service.revision},
        )
    return _response(state, changed)


@router.post(
    "/reset",
    response_model=ConfigResponse,
    summary="Restore the environment defaults",
    description="Discards runtime edits and reloads the values supplied by the environment.",
)
async def reset_config(state: StateDep) -> ConfigResponse:
    state.config_service.reset()
    state.writer.submit_system_event(
        event_type="CONFIG_RESET", message="Configuration reset to environment defaults"
    )
    return _response(state)
