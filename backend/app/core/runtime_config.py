"""Runtime-mutable configuration.

:class:`Settings` is process configuration read once from the environment.  A
subset of it - detection thresholds, the identifier allowlist, retention and
bus parameters - must be tunable at runtime from ``PUT /api/config`` so an
operator can retune a detector during a live demonstration.

The detectors hold a reference to the :class:`ConfigService` rather than to
individual values, so an update takes effect on the very next frame without
rebuilding the detection engine.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import Settings, parse_can_id
from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger

logger = get_logger("core.runtime_config")

#: Fields that only take effect the next time the CAN interface is opened.
RESTART_REQUIRED_FIELDS = frozenset({"can.channel", "can.bitrate", "can.interface"})


class DetectionConfig(BaseModel):
    """Tunable detector thresholds.

    The defaults are *demonstration* values chosen so that attacks are visible
    within seconds on a laptop. They are not derived from any vehicle safety
    standard and must not be treated as such.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    enabled: bool = True
    event_cooldown_seconds: float = Field(default=2.0, ge=0.0, le=300.0)

    # Flood
    flood_threshold: float = Field(default=600.0, gt=0, le=100_000)
    flood_window_seconds: float = Field(default=1.0, gt=0, le=60)
    flood_suspicious_ratio: float = Field(default=0.7, gt=0, le=1.0)
    flood_critical_multiplier: float = Field(default=2.0, ge=1.0, le=100.0)
    per_id_flood_threshold: float = Field(default=200.0, gt=0, le=100_000)

    # Fake speed
    speed_can_id: int = Field(default=0x300, ge=0, le=0x1FFFFFFF)
    fake_speed_threshold: float = Field(default=200.0, gt=0, le=1000)
    fake_speed_suspicious_threshold: float = Field(default=120.0, gt=0, le=1000)
    fake_speed_max_acceleration: float = Field(default=15.0, gt=0, le=500)

    # Identifier allowlist
    allowed_can_ids: list[int] = Field(default_factory=list)
    id_anomaly_escalation_count: int = Field(default=5, ge=1, le=1000)
    id_anomaly_window_seconds: float = Field(default=5.0, gt=0, le=600)

    # Frequency
    frequency_min_samples: int = Field(default=12, ge=3, le=1000)
    frequency_fast_ratio: float = Field(default=2.5, gt=1.0, le=100)
    frequency_slow_ratio: float = Field(default=2.5, gt=1.0, le=100)
    frequency_attack_ratio: float = Field(default=5.0, gt=1.0, le=100)

    @field_validator("allowed_can_ids", mode="before")
    @classmethod
    def _coerce_ids(cls, value: Any) -> list[int]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [part for part in value.split(",") if part.strip()]
        if not isinstance(value, list | tuple | set | frozenset):
            raise ValueError("allowed_can_ids must be a list of CAN identifiers")
        parsed = sorted({parse_can_id(item) for item in value})
        for can_id in parsed:
            if not 0 <= can_id <= 0x1FFFFFFF:
                raise ValueError(f"CAN identifier out of range: {can_id}")
        return parsed

    @model_validator(mode="after")
    def _check_ordering(self) -> Self:
        if self.fake_speed_suspicious_threshold > self.fake_speed_threshold:
            raise ValueError(
                "fake_speed_suspicious_threshold must be <= fake_speed_threshold"
            )
        # A single identifier's rate can never exceed the aggregate bus rate,
        # so a per-identifier threshold above the global one could never fire
        # first - it would be unreachable configuration.
        if self.per_id_flood_threshold > self.flood_threshold:
            raise ValueError(
                "per_id_flood_threshold must not exceed flood_threshold: a single "
                "identifier cannot exceed the aggregate bus rate, so the rule "
                "would be unreachable"
            )
        return self

    @property
    def flood_suspicious_threshold(self) -> float:
        """Rate at or above which traffic is flagged SUSPICIOUS."""
        return self.flood_threshold * self.flood_suspicious_ratio

    @property
    def allowed_can_id_set(self) -> frozenset[int]:
        return frozenset(self.allowed_can_ids)


class CanRuntimeConfig(BaseModel):
    """Bus parameters. Changes apply the next time the monitor is started."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    interface: str = "virtual"
    channel: str = Field(default="can0", min_length=1, max_length=64)
    bitrate: int = Field(default=500_000, ge=1000, le=8_000_000)

    @field_validator("interface")
    @classmethod
    def _check_interface(cls, value: str) -> str:
        allowed = {"virtual", "python-can", "mock"}
        if value not in allowed:
            raise ValueError(f"interface must be one of {sorted(allowed)}")
        return value


class RetentionConfig(BaseModel):
    """Bounds on how much history the database keeps."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    enabled: bool = True
    max_messages: int = Field(default=200_000, ge=1_000, le=50_000_000)
    max_security_events: int = Field(default=50_000, ge=100, le=10_000_000)
    max_system_events: int = Field(default=20_000, ge=100, le=10_000_000)
    max_age_days: int = Field(default=7, ge=1, le=3650)
    persist_can_messages: bool = True


class RuntimeConfig(BaseModel):
    """The complete runtime-tunable configuration document."""

    model_config = ConfigDict(extra="forbid")

    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    can: CanRuntimeConfig = Field(default_factory=CanRuntimeConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)

    @classmethod
    def from_settings(cls, settings: Settings) -> RuntimeConfig:
        """Seed the runtime document from environment-provided defaults."""
        return cls(
            detection=DetectionConfig(
                enabled=settings.detection_enabled,
                event_cooldown_seconds=settings.detection_event_cooldown_seconds,
                flood_threshold=settings.flood_threshold,
                flood_window_seconds=settings.flood_window_seconds,
                flood_suspicious_ratio=settings.flood_suspicious_ratio,
                flood_critical_multiplier=settings.flood_critical_multiplier,
                per_id_flood_threshold=settings.per_id_flood_threshold,
                speed_can_id=settings.speed_can_id_int,
                fake_speed_threshold=settings.fake_speed_threshold,
                fake_speed_suspicious_threshold=settings.fake_speed_suspicious_threshold,
                fake_speed_max_acceleration=settings.fake_speed_max_acceleration,
                allowed_can_ids=sorted(settings.allowed_can_id_set),
                id_anomaly_escalation_count=settings.id_anomaly_escalation_count,
                id_anomaly_window_seconds=settings.id_anomaly_window_seconds,
                frequency_min_samples=settings.frequency_min_samples,
                frequency_fast_ratio=settings.frequency_fast_ratio,
                frequency_slow_ratio=settings.frequency_slow_ratio,
                frequency_attack_ratio=settings.frequency_attack_ratio,
            ),
            can=CanRuntimeConfig(
                interface=settings.can_interface,
                channel=settings.can_channel,
                bitrate=settings.can_bitrate,
            ),
            retention=RetentionConfig(
                enabled=settings.retention_enabled,
                max_messages=settings.retention_max_messages,
                max_security_events=settings.retention_max_security_events,
                max_system_events=settings.retention_max_system_events,
                max_age_days=settings.retention_days,
                persist_can_messages=settings.persist_can_messages,
            ),
        )


ConfigListener = Callable[[RuntimeConfig], None]


class ConfigService:
    """Thread-safe holder for the runtime configuration document."""

    def __init__(self, config: RuntimeConfig, *, defaults: RuntimeConfig | None = None) -> None:
        self._config = config
        self._defaults = defaults or config.model_copy(deep=True)
        self._lock = threading.RLock()
        self._listeners: list[ConfigListener] = []
        self._revision = 1

    @classmethod
    def from_settings(cls, settings: Settings) -> ConfigService:
        config = RuntimeConfig.from_settings(settings)
        return cls(config, defaults=config.model_copy(deep=True))

    # ------------------------------------------------------------------ #
    # Access                                                             #
    # ------------------------------------------------------------------ #
    @property
    def current(self) -> RuntimeConfig:
        return self._config

    @property
    def detection(self) -> DetectionConfig:
        return self._config.detection

    @property
    def revision(self) -> int:
        return self._revision

    def subscribe(self, listener: ConfigListener) -> None:
        """Register a callback invoked after every successful update."""
        self._listeners.append(listener)

    # ------------------------------------------------------------------ #
    # Mutation                                                           #
    # ------------------------------------------------------------------ #
    def update(self, patch: dict[str, Any]) -> tuple[RuntimeConfig, list[str]]:
        """Deep-merge ``patch`` into the current document.

        Returns the new document and the list of changed dotted field paths.
        The update is atomic: if validation fails nothing is applied.
        """
        with self._lock:
            merged = _deep_merge(self._config.model_dump(mode="python"), patch)
            try:
                candidate = RuntimeConfig.model_validate(merged)
            except Exception as exc:
                raise ConfigurationError(f"invalid configuration: {exc}") from exc

            changed = _changed_paths(
                self._config.model_dump(mode="python"), candidate.model_dump(mode="python")
            )
            self._config = candidate
            self._revision += 1

        for listener in list(self._listeners):
            try:
                listener(candidate)
            except Exception as exc:  # pragma: no cover - listener bugs must not break the API
                logger.error(
                    "Configuration listener failed", extra={"context": {"error": str(exc)}}
                )
        if changed:
            logger.info(
                "Runtime configuration updated",
                extra={"context": {"changed": changed, "revision": self._revision}},
            )
        return candidate, changed

    def reset(self) -> RuntimeConfig:
        """Restore the environment-provided defaults."""
        with self._lock:
            self._config = self._defaults.model_copy(deep=True)
            self._revision += 1
        for listener in list(self._listeners):
            try:
                listener(self._config)
            except Exception:  # pragma: no cover
                logger.exception("Configuration listener failed during reset")
        return self._config

    @staticmethod
    def restart_required(changed: list[str]) -> list[str]:
        """Subset of ``changed`` that only applies after a monitor restart."""
        return [path for path in changed if path in RESTART_REQUIRED_FIELDS]


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in patch.items():
        if value is None and key in result and not isinstance(result.get(key), dict):
            continue  # treat explicit nulls as "leave unchanged"
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _changed_paths(before: dict[str, Any], after: dict[str, Any], prefix: str = "") -> list[str]:
    changed: list[str] = []
    for key in sorted(set(before) | set(after)):
        path = f"{prefix}{key}"
        old, new = before.get(key), after.get(key)
        if isinstance(old, dict) and isinstance(new, dict):
            changed.extend(_changed_paths(old, new, prefix=f"{path}."))
        elif old != new:
            changed.append(path)
    return changed
