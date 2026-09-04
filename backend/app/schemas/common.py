"""Response envelopes shared across the API."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ErrorResponse(BaseModel):
    """The shape every failed request returns."""

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "error": "validation_error",
            "message": "the supplied CAN frame is not valid",
            "details": {"errors": [{"field": "arbitration_id", "error": "out of range"}]},
        }
    })

    error: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable explanation.")
    details: dict[str, Any] = Field(default_factory=dict)


class Acknowledgement(BaseModel):
    """Result of a control action."""

    success: bool = True
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class Page(BaseModel, Generic[T]):
    """A page of results with the total match count."""

    items: list[T]
    total: int = Field(description="Total rows matching the filter, ignoring pagination.")
    limit: int
    offset: int
    has_more: bool = False


class HealthResponse(BaseModel):
    """Liveness/readiness payload for ``GET /api/health``."""

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "status": "healthy",
            "service": "can-sentinel",
            "version": "1.0.0",
            "environment": "development",
            "uptime_seconds": 128.4,
            "checks": {"database": {"healthy": True}},
        }
    })

    status: str = Field(description="'healthy' or 'degraded'.")
    service: str
    version: str
    environment: str
    uptime_seconds: float
    checks: dict[str, Any] = Field(default_factory=dict)


class VersionResponse(BaseModel):
    """Build identity, shown on the System page."""

    service: str
    version: str
    environment: str
    api_prefix: str
