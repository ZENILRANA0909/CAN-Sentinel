from src.networking.can_message import CANMessage
from src.networking.can_validator import CANValidator


def test_can_message_creation():
    message = CANMessage(
        can_id=0x100,
        data=[1, 2, 3, 4, 5, 6, 7, 8],
    )

    assert message.can_id == 0x100
    assert message.dlc == 8
    assert message.data == [1, 2, 3, 4, 5, 6, 7, 8]
    assert message.attack_label == "Normal"


def test_can_message_dlc():
    message = CANMessage(
        can_id=0x200,
        data=[10, 20, 30],
    )

    assert message.dlc == 3


def test_valid_standard_can_id():
    message = CANMessage(
        can_id=0x7FF,
        data=[0],
    )

    assert CANValidator.validate(message) is True


def test_invalid_standard_can_id():
    message = CANMessage(
        can_id=0x800,
        data=[0],
    )

    assert CANValidator.validate(message) is False


def test_invalid_can_data_byte():
    message = CANMessage(
        can_id=0x100,
        data=[0, 1, 2, 300],
    )

    assert CANValidator.validate(message) is False


def test_invalid_payload_length():
    message = CANMessage(
        can_id=0x100,
        data=[0] * 9,
    )

    assert CANValidator.validate(message) is False
