import csv

import can

from src.logging.can_logger import CANLogger


def test_can_logger_writes_csv(tmp_path):
    log_file = tmp_path / "can_log.csv"

    logger = CANLogger(log_file)

    message = can.Message(
        arbitration_id=0x123,
        data=[1, 2, 3, 255],
        is_extended_id=False,
    )

    logger.log_message(
        message,
        attack_label="Normal",
    )

    assert log_file.exists()

    with log_file.open(
        "r",
        newline="",
        encoding="utf-8",
    ) as file:
        rows = list(csv.DictReader(file))

    assert len(rows) == 1

    row = rows[0]

    assert row["can_id"] == "0x123"
    assert row["dlc"] == "4"
    assert row["data"] == "01 02 03 FF"
    assert row["attack_label"] == "Normal"
