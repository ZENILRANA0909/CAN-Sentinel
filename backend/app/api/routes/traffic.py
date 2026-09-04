"""Traffic endpoints: recorded frames, live frames, statistics and rate."""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import (
    PaginationDep,
    StateDep,
    page_payload,
    parse_optional_can_id,
    run_in_session,
)
from app.schemas.common import Page
from app.schemas.traffic import (
    CanMessageOut,
    TrafficRateResponse,
    TrafficStatisticsResponse,
)
from app.storage.repositories import CanMessageRepository

router = APIRouter(tags=["traffic"])


@router.get(
    "/messages",
    response_model=Page[CanMessageOut],
    summary="Search recorded CAN traffic",
    description=(
        "Paginated query over the persisted traffic history. For the live view "
        "use `/messages/recent`, which is served from memory and is current "
        "even before the batching writer has committed."
    ),
)
async def list_messages(
    state: StateDep,
    pagination: PaginationDep,
    can_id: Annotated[str | None, Query(description="Filter by identifier, e.g. `0x300`.")] = None,
    since: Annotated[float | None, Query(description="Epoch seconds lower bound.")] = None,
    until: Annotated[float | None, Query(description="Epoch seconds upper bound.")] = None,
    source: Annotated[str | None, Query(description="SIMULATOR, HARDWARE, INJECTED...")] = None,
    flagged_only: Annotated[bool, Query(description="Only frames a detector flagged.")] = False,
    data_contains: Annotated[
        str | None, Query(description="Hex substring of the payload.")
    ] = None,
) -> Page[CanMessageOut]:
    parsed_id = parse_optional_can_id(can_id)
    await state.writer.flush()
    page = await run_in_session(
        state,
        lambda session: CanMessageRepository(session).list(
            limit=pagination.limit,
            offset=pagination.offset,
            can_id=parsed_id,
            since=since,
            until=until,
            source=source,
            flagged_only=flagged_only,
            data_contains=data_contains,
        ),
    )
    return Page[CanMessageOut].model_validate(
        page_payload(page.items, page.total, page.limit, page.offset)
    )


@router.get(
    "/messages/recent",
    response_model=list[CanMessageOut],
    summary="Live CAN frames",
    description=(
        "Newest-first slice of the in-memory ring buffer, including the decoded "
        "signal values and any detector verdict for each frame."
    ),
)
async def recent_messages(
    state: StateDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    can_id: Annotated[str | None, Query(description="Filter by identifier.")] = None,
    flagged_only: Annotated[bool, Query()] = False,
    search: Annotated[str | None, Query(description="Match payload or identifier text.")] = None,
) -> list[CanMessageOut]:
    parsed_id = parse_optional_can_id(can_id)
    rows = state.pipeline.recent_messages(
        limit=limit, can_id=parsed_id, flagged_only=flagged_only, search=search
    )
    return [CanMessageOut.model_validate(row) for row in rows]


@router.get(
    "/traffic/statistics",
    response_model=TrafficStatisticsResponse,
    summary="Traffic statistics",
    description="Live counters plus per-identifier totals from the persisted history.",
)
async def traffic_statistics(
    state: StateDep,
    since_seconds: Annotated[
        float | None, Query(gt=0, description="Restrict stored counts to this many seconds back.")
    ] = None,
) -> TrafficStatisticsResponse:
    snapshot: dict[str, Any] = state.statistics.traffic_snapshot()
    since = (time.time() - since_seconds) if since_seconds else None
    await state.writer.flush()

    def _query(session: Any) -> tuple[int, list[dict[str, Any]]]:
        repo = CanMessageRepository(session)
        return repo.count(), repo.counts_by_can_id(since=since, limit=20)

    stored, by_id = await run_in_session(state, _query)
    snapshot["stored_messages"] = stored
    snapshot["messages_by_can_id"] = by_id
    return TrafficStatisticsResponse.model_validate(snapshot)


@router.get(
    "/traffic/rate",
    response_model=TrafficRateResponse,
    summary="Message rate and recent history",
    description=(
        "Instantaneous rate, the per-second history behind the dashboard chart, "
        "and the flood thresholds so the chart can draw its threshold lines."
    ),
)
async def traffic_rate(
    state: StateDep,
    points: Annotated[int, Query(ge=1, le=300, description="History points to return.")] = 120,
) -> TrafficRateResponse:
    statistics = state.statistics
    detection = state.config_service.detection
    return TrafficRateResponse(
        current_rate_msg_per_s=round(statistics.current_rate(), 2),
        average_rate_msg_per_s=round(statistics.window_rate(), 2),
        peak_rate_msg_per_s=round(statistics.traffic_snapshot()["peak_rate_msg_per_s"], 2),
        window_seconds=state.settings.statistics_window_seconds,
        history=statistics.rate_history(points),
        flood_threshold_msg_per_s=detection.flood_threshold,
        flood_suspicious_threshold_msg_per_s=round(detection.flood_suspicious_threshold, 2),
    )
