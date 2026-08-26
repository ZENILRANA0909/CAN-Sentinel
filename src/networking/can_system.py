import logging

from config.settings import CSV_LOG_FILE
from src.logging.can_logger import CANLogger
from src.networking.can_receiver import CANReceiver
from src.networking.traffic_monitor import CANTrafficMonitor
from src.simulation.ecu_manager import ECUManager


logger = logging.getLogger(__name__)


class CANSystem:
    """
    Coordinates the ECU simulation, CAN receiver,
    traffic monitor, and CAN logger.
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

    def start(self) -> None:
        """Start CAN reception and ECU simulation."""

        logger.info("Starting CAN-Sentinel system.")

        # Start receiver before ECUs.
        self.receiver.start()
        self.ecu_manager.start_all()

        logger.info("CAN-Sentinel system started.")

    def stop(self) -> None:
        """Stop ECUs, receiver, and CAN bus safely."""

        logger.info("Stopping CAN-Sentinel system.")

        # Stop ECUs first so they cannot send new frames.
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
