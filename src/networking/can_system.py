import logging

from config.settings import CSV_LOG_FILE
from src.attacks.attack_manager import AttackManager
from src.logging.can_logger import CANLogger
from src.networking.can_receiver import CANReceiver
from src.networking.traffic_monitor import CANTrafficMonitor
from src.simulation.ecu_manager import ECUManager


logger = logging.getLogger(__name__)


class CANSystem:
    """
    Coordinates the ECU simulation, CAN receiver,
    traffic monitor, CAN logger, and attack manager.
    """

    def __init__(self):
        self.ecu_manager = ECUManager()

        self.receiver = CANReceiver(
            self.ecu_manager.bus
        )

        self.can_logger = CANLogger(
            CSV_LOG_FILE
        )

        self.monitor = CANTrafficMonitor(
            receiver=self.receiver,
            logger_instance=self.can_logger,
        )

        self.attack_manager = AttackManager(
            self.ecu_manager.bus
        )

    def start(self) -> None:
        """Start CAN reception and ECU simulation."""

        logger.info("Starting CAN-Sentinel system.")

        self.receiver.start()
        self.ecu_manager.start_all()

        logger.info("CAN-Sentinel system started.")

    def stop(self) -> None:
        """Stop attacks, ECUs, receiver, and CAN bus."""

        logger.info("Stopping CAN-Sentinel system.")

        # Stop attacks first.
        self.attack_manager.stop_all()

        # Stop simulated ECUs.
        self.ecu_manager.stop_all()

        # Stop CAN receiver.
        self.receiver.stop()

        # Shut down CAN bus.
        try:
            self.ecu_manager.bus.shutdown()
            logger.info("CAN bus shut down successfully.")
        except Exception:
            logger.exception("Error shutting down CAN bus.")

        logger.info("CAN-Sentinel system stopped.")

    def start_fake_speed_attack(self) -> None:
        """Start the fake-speed CAN attack."""

        logger.warning("Starting Fake Speed Attack.")
        self.attack_manager.start_fake_speed()

    def stop_fake_speed_attack(self) -> None:
        """Stop the fake-speed CAN attack."""

        logger.warning("Stopping Fake Speed Attack.")
        self.attack_manager.stop_fake_speed()

    def get_ecu_status(self) -> dict[str, str]:
        """Return the status of all simulated ECUs."""

        return self.ecu_manager.get_status()
