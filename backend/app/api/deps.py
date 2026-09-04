"""FastAPI dependencies.

Routes never import a module-level singleton; they ask for the
:class:`ApplicationState` that was attached to *this* application instance.
That is what makes it possible for the test-suite to spin up a fully isolated
application - own database, own services - per test.
"""

import asyncio
from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.exceptions import CanSentinelError
from app.services.state import ApplicationState

T = TypeVar("T")


def get_state(request: Request) -> ApplicationState:
    """Return the application state bound to the running app."""
    state: ApplicationState | None = getattr(request.app.state, "app_state", None)
    if state is None:  # pragma: no cover - only reachable if startup failed
        raise CanSentinelError("application state is not initialised")
    return state


StateDep = Annotated[ApplicationState, Depends(get_state)]


async def run_in_session(state: ApplicationState, work: Callable[[Session], T]) -> T:
    """Execute a repository call on a worker thread with a scoped session."""

    def _call() -> T:
        with state.database.session() as session:
            return work(session)

    return await asyncio.to_thread(_call)


class Pagination:
    """Shared ``limit``/``offset`` query parameters."""

    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=1000, description="Maximum rows to return.")] = 100,
        offset: Annotated[int, Query(ge=0, description="Rows to skip.")] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


PaginationDep = Annotated[Pagination, Depends(Pagination)]


def parse_optional_can_id(value: str | None) -> int | None:
    """Accept a CAN identifier as ``0x300`` or ``768`` from a query string."""
    if value is None or value == "":
        return None
    text = value.strip().lower()
    try:
        return int(text, 16) if text.startswith("0x") else int(text, 10)
    except ValueError as exc:
        raise CanSentinelError(
            f"invalid CAN identifier: {value!r}",
            details={"hint": "use decimal (768) or hexadecimal (0x300)"},
        ) from exc


def page_payload(items: list[Any], total: int, limit: int, offset: int) -> dict[str, Any]:
    """Uniform pagination envelope."""
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }
