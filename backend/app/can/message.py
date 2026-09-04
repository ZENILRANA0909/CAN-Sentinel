"""The canonical CAN frame model used throughout CAN-Sentinel.

Everything downstream of the interface layer - the pipeline, the detectors, the
storage layer and the API - speaks :class:`CanMessage`.  The model is frozen so
a frame cannot be mutated once it has been admitted to the pipeline, and every
field is validated: an invalid frame never silently enters the system.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

STANDARD_ID_MAX = 0x7FF
EXTENDED_ID_MAX = 0x1FFFFFFF
CLASSIC_MAX_PAYLOAD = 8
FD_MAX_PAYLOAD = 64

# Valid CAN FD payload lengths; classic CAN allows any length up to 8.
FD_DLC_STEPS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64)


class CanDirection(str, Enum):
    """Whether a frame was received from, or transmitted onto, the bus."""

    RX = "RX"
    TX = "TX"


class MessageSource(str, Enum):
    """Provenance of a frame - important when auditing a security event."""

    SIMULATOR = "SIMULATOR"
    HARDWARE = "HARDWARE"
    MOCK = "MOCK"
    INJECTED = "INJECTED"
    REPLAY = "REPLAY"


class MessageType(str, Enum):
    """CAN frame class."""

    DATA = "DATA"
    REMOTE = "REMOTE"
    ERROR = "ERROR"


def coerce_payload(value: Any) -> bytes:
    """Accept bytes, bytearray, ``list[int]`` or a hex string as a payload."""
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray | memoryview):
        return bytes(value)
    if isinstance(value, str):
        text = value.replace("0x", "").replace(" ", "").replace(":", "").replace("-", "")
        if text == "":
            return b""
        if len(text) % 2:
            raise ValueError("hex payload must contain an even number of characters")
        try:
            return bytes.fromhex(text)
        except ValueError as exc:
            raise ValueError(f"invalid hex payload: {value!r}") from exc
    if isinstance(value, list | tuple):
        out = bytearray()
        for item in value:
            if not isinstance(item, int) or isinstance(item, bool):
                raise ValueError("payload list must contain integers")
            if not 0 <= item <= 255:
                raise ValueError(f"payload byte out of range: {item}")
            out.append(item)
        return bytes(out)
    raise ValueError(f"unsupported payload type: {type(value).__name__}")


class CanMessage(BaseModel):
    """An immutable, fully validated CAN frame."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds at which the frame was observed.",
    )
    arbitration_id: int = Field(description="11-bit or 29-bit CAN identifier.")
    is_extended_id: bool = Field(default=False, description="True for 29-bit identifiers.")
    dlc: int = Field(
        default=-1, description="Data length code; derived from the payload when omitted."
    )
    data: bytes = Field(default=b"", description="Frame payload.")
    channel: str = Field(default="vcan0", max_length=64)
    direction: CanDirection = CanDirection.RX
    source: MessageSource = MessageSource.SIMULATOR
    message_type: MessageType = MessageType.DATA
    is_fd: bool = Field(
        default=False, description="True for a CAN FD frame (payload up to 64 bytes)."
    )

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    @field_validator("data", mode="before")
    @classmethod
    def _validate_payload(cls, value: Any) -> bytes:
        return coerce_payload(value)

    @field_validator("timestamp")
    @classmethod
    def _validate_timestamp(cls, value: float) -> float:
        if value < 0:
            raise ValueError("timestamp must not be negative")
        return float(value)

    @field_validator("channel")
    @classmethod
    def _validate_channel(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("channel must not be empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_frame(self) -> Self:
        limit = EXTENDED_ID_MAX if self.is_extended_id else STANDARD_ID_MAX
        if self.arbitration_id < 0:
            raise ValueError("arbitration_id must not be negative")
        if self.arbitration_id > limit:
            kind = "extended (29-bit)" if self.is_extended_id else "standard (11-bit)"
            raise ValueError(
                f"arbitration_id 0x{self.arbitration_id:X} exceeds the {kind} range "
                f"(max 0x{limit:X})"
            )

        max_payload = FD_MAX_PAYLOAD if self.is_fd else CLASSIC_MAX_PAYLOAD
        if len(self.data) > max_payload:
            bus = "CAN FD" if self.is_fd else "classic CAN"
            raise ValueError(
                f"payload of {len(self.data)} bytes exceeds the {bus} limit of {max_payload}"
            )
        if self.is_fd and len(self.data) not in FD_DLC_STEPS:
            raise ValueError(f"{len(self.data)} is not a valid CAN FD payload length")

        if self.dlc == -1:
            object.__setattr__(self, "dlc", len(self.data))
        elif self.dlc != len(self.data) and self.message_type is not MessageType.REMOTE:
            raise ValueError(f"dlc {self.dlc} does not match the {len(self.data)}-byte payload")
        if not 0 <= self.dlc <= max_payload:
            raise ValueError(f"dlc {self.dlc} is outside the valid range 0..{max_payload}")
        return self

    # ------------------------------------------------------------------ #
    # Derived views                                                      #
    # ------------------------------------------------------------------ #
    @property
    def can_id_hex(self) -> str:
        width = 8 if self.is_extended_id else 3
        return f"0x{self.arbitration_id:0{width}X}"

    @property
    def data_hex(self) -> str:
        return self.data.hex().upper()

    @property
    def data_hex_spaced(self) -> str:
        return " ".join(f"{byte:02X}" for byte in self.data)

    @property
    def datetime_utc(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp, tz=UTC)

    @property
    def iso_timestamp(self) -> str:
        return self.datetime_utc.isoformat()

    # ------------------------------------------------------------------ #
    # Interop                                                            #
    # ------------------------------------------------------------------ #
    def to_wire(self) -> dict[str, Any]:
        """Compact JSON-safe representation used by the REST API and WebSocket."""
        return {
            "timestamp": self.timestamp,
            "iso_timestamp": self.iso_timestamp,
            "can_id": self.arbitration_id,
            "can_id_hex": self.can_id_hex,
            "is_extended_id": self.is_extended_id,
            "dlc": self.dlc,
            "data": self.data_hex,
            "channel": self.channel,
            "direction": self.direction.value,
            "source": self.source.value,
            "message_type": self.message_type.value,
        }

    @classmethod
    def from_python_can(
        cls,
        msg: Any,
        *,
        channel: str | None = None,
        source: MessageSource = MessageSource.HARDWARE,
    ) -> CanMessage:
        """Build a :class:`CanMessage` from a ``can.Message`` instance."""
        resolved = channel or (str(msg.channel) if getattr(msg, "channel", None) else "can0")
        message_type = MessageType.DATA
        if getattr(msg, "is_error_frame", False):
            message_type = MessageType.ERROR
        elif getattr(msg, "is_remote_frame", False):
            message_type = MessageType.REMOTE
        payload = bytes(msg.data or b"")
        dlc = int(getattr(msg, "dlc", 0)) if message_type is MessageType.REMOTE else len(payload)
        return cls(
            timestamp=float(getattr(msg, "timestamp", 0.0) or time.time()),
            arbitration_id=int(msg.arbitration_id),
            is_extended_id=bool(getattr(msg, "is_extended_id", False)),
            dlc=dlc,
            data=payload,
            channel=resolved,
            direction=CanDirection.RX,
            source=source,
            message_type=message_type,
            is_fd=bool(getattr(msg, "is_fd", False)),
        )

    def to_python_can(self) -> Any:
        """Convert to a ``can.Message``. Requires ``python-can`` to be installed."""
        import can  # imported lazily so the core never hard-depends on the driver

        return can.Message(
            timestamp=self.timestamp,
            arbitration_id=self.arbitration_id,
            is_extended_id=self.is_extended_id,
            dlc=self.dlc,
            data=self.data,
            channel=self.channel,
            is_fd=self.is_fd,
            is_remote_frame=self.message_type is MessageType.REMOTE,
            is_error_frame=self.message_type is MessageType.ERROR,
        )

    def __str__(self) -> str:  # pragma: no cover - debugging convenience
        return f"[{self.iso_timestamp}] {self.can_id_hex} [{self.dlc}] {self.data_hex_spaced}"
