import csv
from pathlib import Path

import can

from src.logging.can_logger import CANLogger
from src.networking.can_interface import CANInterface
from src.networking.can_receiver import CANReceiver
from src.networking.traffic_monitor import CANTrafficMonitor


def test_fake_speed_attack_is_logged(tmp_path: Path):
    log_file = tmp_path / "attack_log.csv"

    bus = CANInterface()
    receiver = CANReceiver(bus)
    logger = CANLogger(log_file)

    CANTrafficMonitor(
        receiver=receiver,
        logger_instance=logger,
    )

    try:
        message = can.Message(
            arbitration_id=0x300,
            data=[250, 0, 0, 0, 0, 0, 0, 0],
            is_extended_id=False,
        )

        receiver.callback(message)

        with log_file.open(
            "r",
            newline="",
            encoding="utf-8",
        ) as file:
            rows = list(csv.DictReader(file))

        assert len(rows) == 1
        assert rows[0]["can_id"] == "0x300"
        assert rows[0]["attack_label"] == "Fake Speed Attack"
        assert rows[0]["dlc"] == "8"

    finally:
        bus.shutdown()
