import sys
from pathlib import Path

import can

# Add the project root to Python's import path.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import CSV_LOG_FILE
from src.logging.can_logger import CANLogger


def main() -> None:
    """Create and log a sample CAN message."""

    logger = CANLogger(CSV_LOG_FILE)

    message = can.Message(
        arbitration_id=0x100,
        data=[10, 20, 30, 40],
        is_extended_id=False,
    )

    logger.log_message(
        message,
        attack_label="Normal",
    )

    print(f"CAN message logged to: {CSV_LOG_FILE}")


if __name__ == "__main__":
    main()
