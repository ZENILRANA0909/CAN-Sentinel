import csv
import threading
from datetime import datetime
from pathlib import Path

import can


class CANLogger:
    """
    Thread-safe CSV logger for CAN traffic.

    Each received CAN frame is stored with:
    - Timestamp
    - CAN ID
    - DLC
    - Data bytes
    - Attack label
    """

    HEADERS = [
        "timestamp",
        "can_id",
        "dlc",
        "data",
        "attack_label",
    ]

    def __init__(self, log_file: Path):
        self.log_file = Path(log_file)
        self._lock = threading.Lock()

        self.log_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._initialize_file()

    def _initialize_file(self) -> None:
        """Create the CSV file with headers if necessary."""

        if self.log_file.exists() and self.log_file.stat().st_size > 0:
            return

        with self.log_file.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=self.HEADERS,
            )

            writer.writeheader()

    def log_message(
        self,
        message: can.Message,
        attack_label: str = "Normal",
    ) -> None:
        """
        Store a CAN message in the CSV log.

        Args:
            message: Received python-can message.
            attack_label: Classification associated with the message.
        """

        timestamp = datetime.now().isoformat(
            timespec="milliseconds"
        )

        data = " ".join(
            f"{byte:02X}"
            for byte in message.data
        )

        row = {
            "timestamp": timestamp,
            "can_id": f"0x{message.arbitration_id:X}",
            "dlc": message.dlc,
            "data": data,
            "attack_label": attack_label,
        }

        with self._lock:
            with self.log_file.open(
                "a",
                newline="",
                encoding="utf-8",
            ) as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=self.HEADERS,
                )

                writer.writerow(row)
