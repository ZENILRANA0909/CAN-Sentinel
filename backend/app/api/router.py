"""API router assembly."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import config, monitor, security, simulation, system, traffic


def build_api_router(prefix: str = "/api") -> APIRouter:
    """Aggregate every REST route under the configured prefix."""
    router = APIRouter(prefix=prefix.rstrip("/"))
    router.include_router(system.router)
    router.include_router(traffic.router)
    router.include_router(security.router)
    router.include_router(simulation.router)
    router.include_router(monitor.router)
    router.include_router(config.router)
    return router
