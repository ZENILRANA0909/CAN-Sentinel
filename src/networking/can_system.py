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
        # Create the ECU manager and shared CAN bus.
        self.ecu_manager = ECUManager()

        # Create the CAN receiver.
        self.receiver = CANReceiver(
            self.ecu_manager.bus
        )

        # Create the CAN traffic logger.
        self.can_logger = CANLogger(
            CSV_LOG_FILE
        )

        # Create the traffic monitor.
        self.monitor = CANTrafficMonitor(
            receiver=self.receiver,
            logger_instance=self.can_logger,
        )

        # Create the attack manager using the same CAN bus.
        self.attack_manager = AttackManager(
            self.ecu_manager.bus
        )

    def start(self) -> None:
        """Start CAN reception and ECU simulation."""

        logger.info("Starting CAN-Sentinel system.")

        # Start receiver before ECUs.
        self.receiver.start()

        # Start all simulated ECUs.
        self.ecu_manager.start_all()

        logger.info("CAN-Sentinel system started.")

    def stop(self) -> None:
        """Stop attacks, ECUs, receiver, and CAN bus safely."""

        logger.info("Stopping CAN-Sentinel system.")

        # Stop all active attacks first.
        self.attack_manager.stop_all()

        # Stop ECUs so they cannot send new frames.
        self.ecu_manager.stop_all()

        # Stop the receiver thread.
        self.receiver.stop()

        # Shut down the shared CAN bus.
        try:
            self.ecu_manager.bus.shutdown()
            logger.info("CAN bus shut down successfully.")
        except Exception:
            logger.exception("Error shutting down CAN bus.")

        logger.info("CAN-Sentinel system stopped.")

    def get_ecu_status(self) -> dict[str, str]:
        """Return the status of all simulated ECUs."""

        return self.ecu_manager.get_status()
