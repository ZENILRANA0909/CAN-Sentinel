from src.attacks.attack_manager import AttackManager
from src.networking.can_interface import CANInterface


def test_attack_manager_fake_speed():
    bus = CANInterface()
    manager = AttackManager(bus)

    manager.start_fake_speed()

    try:
        message = bus.receive(timeout=1.0)

        assert message is not None
        assert message.arbitration_id == 0x300
        assert message.data[0] == 250

    finally:
        manager.stop_all()
        bus.shutdown()
