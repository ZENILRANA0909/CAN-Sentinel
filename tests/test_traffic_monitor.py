import csv
import time

from src.logging.can_logger import CANLogger
from src.networking.can_interface import CANInterface
from src.networking.can_receiver import CANReceiver
from src.networking.traffic_monitor import CANTrafficMonitor


def test_receiver_logs_received_message(tmp_path):
    log_file = tmp_path / "traffic.csv"

    bus = CANInterface()

    receiver = CANReceiver(bus)
    logger_instance = CANLogger(log_file)

    CANTrafficMonitor(
        receiver=receiver,
        logger_instance=logger_instance,
    )

    try:
        receiver.start()

        bus.send(
            arbitration_id=0x321,
            data=[10, 20, 30, 40],
        )

        deadline = time.time() + 2.0

        while time.time() < deadline:
            if log_file.exists() and log_file.stat().st_size > 0:
                break

            time.sleep(0.01)

        receiver.stop()

        with log_file.open(
            "r",
            newline="",
            encoding="utf-8",
        ) as file:
            rows = list(csv.DictReader(file))

        assert len(rows) == 1
        assert rows[0]["can_id"] == "0x321"
        assert rows[0]["dlc"] == "4"
        assert rows[0]["data"] == "0A 14 1E 28"
        assert rows[0]["attack_label"] == "Normal"

    finally:
        receiver.stop()
        bus.shutdown()
