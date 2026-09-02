import can

from src.networking.traffic_monitor import CANTrafficMonitor


class DummyLogger:
    def __init__(self):
        self.messages = []

    def log_message(self, message, attack_label="Normal"):
        self.messages.append((message, attack_label))


def test_fake_speed_detection_manual():
    logger = DummyLogger()

    monitor = CANTrafficMonitor(
        receiver=None,
        logger_instance=logger,
    )

    message = can.Message(
        arbitration_id=0x300,
        data=[250, 0, 0, 0, 0, 0, 0, 0],
        is_extended_id=False,
    )

    result = monitor.detect_attack(message)

    print("Detection result:", result)

    assert result == "Fake Speed Attack"
