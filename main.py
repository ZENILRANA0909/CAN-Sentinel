import logging
import time

from config.logging_config import configure_logging
from src.networking.can_system import CANSystem


def main() -> None:
    """Start CAN-Sentinel and demonstrate CAN attack detection."""

    configure_logging()

    logger = logging.getLogger(__name__)

    logger.info("===== CAN-Sentinel =====")
    logger.info("Starting CAN monitoring system...")

    system = CANSystem()

    system.start()

    try:
        logger.info("Normal CAN traffic is running.")

        # Allow normal traffic to run first.
        time.sleep(5)

        # Start the fake-speed attack.
        logger.warning("===== STARTING FAKE SPEED ATTACK =====")
        system.start_fake_speed_attack()

        # Keep the attack active for demonstration.
        time.sleep(5)

        # Stop the attack.
        logger.warning("===== STOPPING FAKE SPEED ATTACK =====")
        system.stop_fake_speed_attack()

        # Allow normal traffic to continue.
        time.sleep(3)

    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")

    finally:
        system.stop()
        logger.info("CAN-Sentinel stopped.")


if __name__ == "__main__":
    main()
