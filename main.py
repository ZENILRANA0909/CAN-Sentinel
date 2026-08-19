import logging
import time

from config.logging_config import configure_logging
from src.simulation.ecu_manager import ECUManager


def main() -> None:
    """Start CAN-Sentinel ECU simulation."""

    configure_logging()

    logger = logging.getLogger(__name__)

    logger.info("===== CAN-Sentinel =====")
    logger.info("Starting vehicle simulation...")

    manager = ECUManager()

    manager.start_all()

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")

    finally:
        manager.stop_all()
        logger.info("CAN-Sentinel stopped.")


if __name__ == "__main__":
    main()
