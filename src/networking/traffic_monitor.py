import logging

import can

from src.logging.can_logger import CANLogger
from src.networking.can_receiver import CANReceiver


logger = logging.getLogger(__name__)


class CANTrafficMonitor:
    """
    Connects the CAN receiver with the CAN traffic logger.

    Every received CAN frame is automatically forwarded to
    the logger and stored in the configured CSV file.
    """

    def __init__(
        self,
        receiver: CANReceiver,
        logger_instance: CANLogger,
    ):
        self.receiver = receiver
        self.logger = logger_instance

        self.receiver.callback = self._handle_message

    def _handle_message(self, message: can.Message) -> None:
        """
        Process a received CAN frame and store it in the log.
        """

        try:
            self.logger.log_message(
                message,
                attack_label="Normal",
            )

        except Exception:
            logger.exception(
                "Failed to log CAN message."
            )
