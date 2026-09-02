from src.attacks.base_attack import BaseAttack
from src.networking.can_interface import CANInterface


class DummyAttack(BaseAttack):

    def run(self) -> None:
        while self.running:
            break


def test_attack_start_and_stop():
    bus = CANInterface()

    attack = DummyAttack(bus)

    attack.start()
    attack.stop()

    assert attack.running is False

    bus.shutdown()
