"""Security endpoints: detected attacks, statistics and triage."""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query

from app.api.deps import (
    PaginationDep,
    StateDep,
    page_payload,
    parse_optional_can_id,
    run_in_session,
)
from app.core.exceptions import ResourceNotFoundError
from app.detection.base import AttackType, Severity
from app.models.security_event import EventStatus
from app.schemas.common import Page
from app.schemas.security import (
    AttackStatisticsResponse,
    EventStatusUpdate,
    SecurityEventOut,
    SecuritySummaryResponse,
)
from app.storage.repositories import SecurityEventRepository

router = APIRouter(tags=["security"])

HOUR_SECONDS = 3600.0


@router.get(
    "/attacks",
    response_model=Page[SecurityEventOut],
    summary="Search detected security events",
)
async def list_attacks(
    state: StateDep,
    pagination: PaginationDep,
    attack_type: Annotated[AttackType | None, Query(description="Filter by attack type.")] = None,
    severity: Annotated[Severity | None, Query(description="Filter by severity.")] = None,
    status: Annotated[EventStatus | None, Query(description="Filter by triage status.")] = None,
    detector: Annotated[str | None, Query(description="Filter by detector name.")] = None,
    can_id: Annotated[str | None, Query(description="Filter by identifier, e.g. `0x300`.")] = None,
    since: Annotated[float | None, Query(description="Epoch seconds lower bound.")] = None,
    until: Annotated[float | None, Query(description="Epoch seconds upper bound.")] = None,
) -> Page[SecurityEventOut]:
    parsed_id = parse_optional_can_id(can_id)
    await state.writer.flush()
    page = await run_in_session(
        state,
        lambda session: SecurityEventRepository(session).list(
            limit=pagination.limit,
            offset=pagination.offset,
            attack_type=attack_type.value if attack_type else None,
            severity=severity.value if severity else None,
            status=status.value if status else None,
            detector=detector,
            can_id=parsed_id,
            since=since,
            until=until,
        ),
    )
    return Page[SecurityEventOut].model_validate(
        page_payload(page.items, page.total, page.limit, page.offset)
    )


@router.get(
    "/attacks/recent",
    response_model=list[SecurityEventOut],
    summary="Most recent security events",
    description="Served from the persisted history so event IDs are available for triage.",
)
async def recent_attacks(
    state: StateDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[SecurityEventOut]:
    await state.writer.flush()
    rows = await run_in_session(
        state, lambda session: SecurityEventRepository(session).recent(limit)
    )
    return [SecurityEventOut.model_validate(row) for row in rows]


@router.get(
    "/attacks/statistics",
    response_model=AttackStatisticsResponse,
    summary="Attack statistics and timeline",
    description="Distribution by type, severity, status and detector, plus a bucketed timeline.",
)
async def attack_statistics(
    state: StateDep,
    since_seconds: Annotated[float | None, Query(gt=0)] = None,
    bucket_seconds: Annotated[int, Query(ge=1, le=3600)] = 60,
    buckets: Annotated[int, Query(ge=1, le=500)] = 60,
) -> AttackStatisticsResponse:
    await state.writer.flush()
    since = (time.time() - since_seconds) if since_seconds else None
    hour_ago = time.time() - HOUR_SECONDS

    def _query(session: Any) -> dict[str, Any]:
        repo = SecurityEventRepository(session)
        return {
            "total_events": repo.count(since=since),
            "events_last_hour": repo.count(since=hour_ago),
            "by_attack_type": repo.counts_by("attack_type", since=since),
            "by_severity": repo.counts_by("severity", since=since),
            "by_status": repo.counts_by("status", since=since),
            "by_detector": repo.counts_by("detector", since=since),
            "top_can_ids": repo.top_can_ids(limit=10, since=since),
            "timeline": repo.timeline(
                bucket_seconds=bucket_seconds, since=since, buckets=buckets
            ),
        }

    payload = await run_in_session(state, _query)
    security = state.statistics.security_snapshot()
    return AttackStatisticsResponse(
        **payload,
        live_attacks_total=security["attacks_total"],
        active_alerts=security["active_alerts"],
        threat_level=security["threat_level"],
        bucket_seconds=bucket_seconds,
    )


@router.get(
    "/security/summary",
    response_model=SecuritySummaryResponse,
    summary="Dashboard security summary",
    description="Single call backing the dashboard header, alert list and detector panel.",
)
async def security_summary(
    state: StateDep,
    limit: Annotated[int, Query(ge=1, le=100, description="Recent events to include.")] = 10,
) -> SecuritySummaryResponse:
    await state.writer.flush()
    hour_ago = time.time() - HOUR_SECONDS

    def _query(session: Any) -> dict[str, Any]:
        repo = SecurityEventRepository(session)
        return {
            "events_stored": repo.count(),
            "events_last_hour": repo.count(since=hour_ago),
            "recent_events": repo.recent(limit),
        }

    stored = await run_in_session(state, _query)
    security = state.statistics.security_snapshot()
    detectors = state.engine.snapshot()["detectors"]
    return SecuritySummaryResponse(
        threat_level=security["threat_level"],
        active_alerts=security["active_alerts"],
        attacks_total=security["attacks_total"],
        events_stored=stored["events_stored"],
        events_last_hour=stored["events_last_hour"],
        by_attack_type=security["by_attack_type"],
        by_severity=security["by_severity"],
        recent_events=[SecurityEventOut.model_validate(row) for row in stored["recent_events"]],
        detectors=detectors,
        monitor_running=state.monitor.is_running,
        simulation_running=state.simulation.is_running,
    )


@router.get(
    "/attacks/{event_id}",
    response_model=SecurityEventOut,
    summary="Fetch one security event",
)
async def get_attack(
    state: StateDep,
    event_id: Annotated[int, Path(ge=1)],
) -> SecurityEventOut:
    await state.writer.flush()
    row = await run_in_session(
        state, lambda session: SecurityEventRepository(session).get(event_id)
    )
    if row is None:
        raise ResourceNotFoundError(f"security event {event_id} does not exist")
    return SecurityEventOut.model_validate(row)


@router.patch(
    "/attacks/{event_id}",
    response_model=SecurityEventOut,
    summary="Triage a security event",
    description="Move an event between NEW, ACKNOWLEDGED and RESOLVED.",
)
async def update_attack_status(
    state: StateDep,
    payload: EventStatusUpdate,
    event_id: Annotated[int, Path(ge=1)],
) -> SecurityEventOut:
    await state.writer.flush()
    row = await run_in_session(
        state,
        lambda session: SecurityEventRepository(session).set_status(event_id, payload.status),
    )
    if row is None:
        raise ResourceNotFoundError(f"security event {event_id} does not exist")
    state.writer.submit_system_event(
        event_type="EVENT_TRIAGED",
        message=f"Security event {event_id} marked {payload.status.value}",
        context={"event_id": event_id, "status": payload.status.value},
    )
    return SecurityEventOut.model_validate(row)
