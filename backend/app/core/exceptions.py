"""Application specific exception hierarchy.

Every error raised deliberately by CAN-Sentinel derives from
:class:`CanSentinelError`, which lets the API layer translate internal failures
into consistent HTTP problem responses instead of leaking stack traces.
"""

from __future__ import annotations

from typing import Any


class CanSentinelError(Exception):
    """Base class for all CAN-Sentinel errors."""

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {"error": self.error_code, "message": self.message, "details": self.details}


class ValidationError(CanSentinelError):
    """A supplied value failed domain validation."""

    status_code = 422
    error_code = "validation_error"


class InvalidCanMessageError(ValidationError):
    """A CAN frame could not be accepted into the pipeline."""

    error_code = "invalid_can_message"


class ConfigurationError(CanSentinelError):
    """The requested configuration is not usable."""

    status_code = 400
    error_code = "configuration_error"


class CanInterfaceError(CanSentinelError):
    """The CAN interface could not be opened or used."""

    status_code = 503
    error_code = "can_interface_error"


class SimulationError(CanSentinelError):
    """The traffic simulator could not perform the requested transition."""

    status_code = 409
    error_code = "simulation_error"


class MonitorError(CanSentinelError):
    """The monitoring service could not perform the requested transition."""

    status_code = 409
    error_code = "monitor_error"


class StorageError(CanSentinelError):
    """A database operation failed."""

    status_code = 503
    error_code = "storage_error"


class ResourceNotFoundError(CanSentinelError):
    """A requested resource does not exist."""

    status_code = 404
    error_code = "not_found"
