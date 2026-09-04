"""CAN frame validation.

An invalid frame must be rejected at the boundary, never silently accepted.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.can.message import (
    CLASSIC_MAX_PAYLOAD,
    EXTENDED_ID_MAX,
    STANDARD_ID_MAX,
    CanDirection,
    CanMessage,
    MessageSource,
    MessageType,
    coerce_payload,
)


class TestPayloadCoercion:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (b"\x01\x02", b"\x01\x02"),
            (bytearray(b"\xaa"), b"\xaa"),
            ("0102", b"\x01\x02"),
            ("01 02", b"\x01\x02"),
            ("01:02", b"\x01\x02"),
            ("0x0102", b"\x01\x02"),
            ("", b""),
            ([1, 2, 255], b"\x01\x02\xff"),
            ((0,), b"\x00"),
        ],
    )
    def test_accepts_supported_representations(self, value: object, expected: bytes) -> None:
        assert coerce_payload(value) == expected

    @pytest.mark.parametrize("value", ["0", "ZZ", [256], [-1], [True], 42, None, 1.5])
    def test_rejects_invalid_representations(self, value: object) -> None:
        with pytest.raises(ValueError):
            coerce_payload(value)


class TestIdentifierValidation:
    def test_accepts_maximum_standard_id(self) -> None:
        assert CanMessage(arbitration_id=STANDARD_ID_MAX).arbitration_id == STANDARD_ID_MAX

    def test_rejects_standard_id_above_11_bits(self) -> None:
        with pytest.raises(ValidationError, match="standard"):
            CanMessage(arbitration_id=STANDARD_ID_MAX + 1)

    def test_accepts_extended_id_when_flagged(self) -> None:
        message = CanMessage(arbitration_id=0x1FFFF, is_extended_id=True)
        assert message.is_extended_id
        assert message.can_id_hex == "0x0001FFFF"

    def test_rejects_extended_id_above_29_bits(self) -> None:
        with pytest.raises(ValidationError, match="extended"):
            CanMessage(arbitration_id=EXTENDED_ID_MAX + 1, is_extended_id=True)

    def test_rejects_negative_id(self) -> None:
        with pytest.raises(ValidationError):
            CanMessage(arbitration_id=-1)


class TestPayloadValidation:
    def test_accepts_maximum_classic_payload(self) -> None:
        message = CanMessage(arbitration_id=0x100, data=b"\x11" * CLASSIC_MAX_PAYLOAD)
        assert message.dlc == CLASSIC_MAX_PAYLOAD

    def test_rejects_payload_beyond_classic_limit(self) -> None:
        with pytest.raises(ValidationError, match="classic CAN limit"):
            CanMessage(arbitration_id=0x100, data=b"\x11" * (CLASSIC_MAX_PAYLOAD + 1))

    def test_accepts_can_fd_payload(self) -> None:
        message = CanMessage(arbitration_id=0x100, data=b"\x11" * 64, is_fd=True)
        assert message.dlc == 64

    def test_rejects_invalid_fd_length(self) -> None:
        # 9 bytes is not one of the discrete CAN FD payload sizes.
        with pytest.raises(ValidationError, match="not a valid CAN FD payload length"):
            CanMessage(arbitration_id=0x100, data=b"\x11" * 9, is_fd=True)

    def test_derives_dlc_from_payload(self) -> None:
        assert CanMessage(arbitration_id=0x100, data=b"\x01\x02\x03").dlc == 3

    def test_rejects_dlc_mismatch(self) -> None:
        with pytest.raises(ValidationError, match="does not match"):
            CanMessage(arbitration_id=0x100, data=b"\x01\x02", dlc=5)

    def test_remote_frame_may_declare_dlc_without_payload(self) -> None:
        message = CanMessage(
            arbitration_id=0x100, data=b"", dlc=8, message_type=MessageType.REMOTE
        )
        assert message.dlc == 8


class TestFrameProperties:
    def test_rejects_negative_timestamp(self) -> None:
        with pytest.raises(ValidationError, match="negative"):
            CanMessage(arbitration_id=0x100, timestamp=-1.0)

    def test_rejects_blank_channel(self) -> None:
        with pytest.raises(ValidationError):
            CanMessage(arbitration_id=0x100, channel="   ")

    def test_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError):
            CanMessage(arbitration_id=0x100, bogus_field=1)  # type: ignore[call-arg]

    def test_is_immutable(self) -> None:
        message = CanMessage(arbitration_id=0x100)
        with pytest.raises(ValidationError):
            message.arbitration_id = 0x200  # type: ignore[misc]

    def test_hex_formatting(self) -> None:
        message = CanMessage(arbitration_id=0x300, data=b"\xde\xad\xbe\xef")
        assert message.can_id_hex == "0x300"
        assert message.data_hex == "DEADBEEF"
        assert message.data_hex_spaced == "DE AD BE EF"

    def test_iso_timestamp_is_utc(self) -> None:
        message = CanMessage(arbitration_id=0x100, timestamp=0.0)
        assert message.iso_timestamp.startswith("1970-01-01T00:00:00")
        assert message.iso_timestamp.endswith("+00:00")

    def test_to_wire_round_trips_the_essentials(self) -> None:
        message = CanMessage(
            arbitration_id=0x300,
            data=b"\x01\x02",
            source=MessageSource.INJECTED,
            direction=CanDirection.TX,
        )
        wire = message.to_wire()
        assert wire["can_id"] == 0x300
        assert wire["can_id_hex"] == "0x300"
        assert wire["data"] == "0102"
        assert wire["dlc"] == 2
        assert wire["source"] == "INJECTED"
        assert wire["direction"] == "TX"


class TestPythonCanInterop:
    def test_round_trips_through_python_can(self) -> None:
        original = CanMessage(
            arbitration_id=0x1AB, data=b"\x01\x02\x03", timestamp=1700000000.5, channel="can0"
        )
        restored = CanMessage.from_python_can(original.to_python_can(), channel="can0")
        assert restored.arbitration_id == original.arbitration_id
        assert restored.data == original.data
        assert restored.dlc == original.dlc
        assert restored.timestamp == original.timestamp
        assert restored.source is MessageSource.HARDWARE

    def test_maps_error_frames(self) -> None:
        import can

        raw = can.Message(arbitration_id=0x1, is_error_frame=True, data=b"", timestamp=1.0)
        message = CanMessage.from_python_can(raw)
        assert message.message_type is MessageType.ERROR
