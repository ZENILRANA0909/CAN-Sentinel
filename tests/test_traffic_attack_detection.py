import can

from src.networking.can_receiver import CANReceiver
from src.networking.can_interface import CANInterface
from src.networking.traffic_monitor import CANTrafficMonitor


class DummyLogger:
    def __init__(self):
        self.attack_label = None

    def log_message(self, message, attack_label="Normal"):
        self.attack_label = attack_label


def create_monitor():
    bus = CANInterface()
    receiver = CANReceiver(bus)
    logger = DummyLogger()

    monitor = CANTrafficMonitor(
        receiver=receiver,
        logger_instance=logger,
    )

    return monitor, bus


def test_fake_speed_attack_detection():
    monitor, bus = create_monitor()

    try:
        message = can.Message(
            arbitration_id=0x300,
            data=[250, 0, 0, 0, 0, 0, 0, 0],
            is_extended_id=False,
        )

        assert monitor.detect_attack(message) == "Fake Speed Attack"

    finally:
        bus.shutdown()


def test_normal_speed_is_not_attack():
    monitor, bus = create_monitor()

    try:
        message = can.Message(
            arbitration_id=0x300,
            data=[100, 0, 0, 0, 0, 0, 0, 0],
            is_extended_id=False,
        )

        assert monitor.detect_attack(message) == "Normal"

    finally:
        bus.shutdown()
