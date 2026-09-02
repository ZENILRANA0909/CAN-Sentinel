import can

from src.networking.traffic_monitor import CANTrafficMonitor


class DummyLogger:
    def log_message(self, message, attack_label):
        pass


def test_can_flood_attack_detection():
    monitor = CANTrafficMonitor(
        receiver=None,
        logger_instance=DummyLogger(),
    )

    detected = "Normal"

    for _ in range(25):
        message = can.Message(
            arbitration_id=0x555,
            data=[0, 0, 0, 0, 0, 0, 0, 0],
            is_extended_id=False,
        )

        detected = monitor.detect_attack(message)

    print(f"Detection result: {detected}")

    assert detected == "CAN Flood Attack"
