import time

from src.attacks.fake_speed_attack import FakeSpeedAttack
from src.networking.can_interface import CANInterface


def test_fake_speed_attack_sends_message():
    bus = CANInterface()

    attack = FakeSpeedAttack(
        bus=bus,
        fake_speed=250,
        interval=0.05,
    )

    attack.start()

    try:
        message = bus.receive(timeout=1.0)

        assert message is not None
        assert message.arbitration_id == 0x300
        assert message.data[0] == 250
        assert message.dlc == 8

    finally:
        attack.stop()
        bus.shutdown()
