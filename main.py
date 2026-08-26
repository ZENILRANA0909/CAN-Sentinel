import logging
import time

from config.logging_config import configure_logging
from src.networking.can_system import CANSystem


def main() -> None:
    """Start the complete CAN-Sentinel system."""

    configure_logging()

    logger = logging.getLogger(__name__)

    logger.info("===== CAN-Sentinel =====")
    logger.info("Starting CAN monitoring system...")

    system = CANSystem()

    system.start()

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")

    finally:
        system.stop()
        logger.info("CAN-Sentinel stopped.")


if __name__ == "__main__":
    main()
