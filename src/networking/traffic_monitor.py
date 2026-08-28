import logging

import can

from src.logging.can_logger import CANLogger
from src.networking.can_receiver import CANReceiver


logger = logging.getLogger(__name__)


class CANTrafficMonitor:
    """
    Monitors received CAN traffic and classifies messages.

    Current detection rules:
    - CAN ID 0x300 with speed >= 200 is classified
      as a Fake Speed Attack.
    - All other messages are classified as Normal.
    """

    SPEED_CAN_ID = 0x300
    FAKE_SPEED_THRESHOLD = 200

    def __init__(
        self,
        receiver: CANReceiver,
        logger_instance: CANLogger,
    ):
        self.receiver = receiver
        self.logger = logger_instance

        # Register this monitor as the receiver callback.
        self.receiver.callback = self.process_message

    def process_message(self, message: can.Message) -> None:
        """
        Analyze and classify a received CAN message.
        """

        attack_label = self.detect_attack(message)

        if attack_label != "Normal":
            logger.warning(
                "ATTACK DETECTED: %s | CAN ID=%s | DATA=%s",
                attack_label,
                hex(message.arbitration_id),
                list(message.data),
            )

        self.logger.log_message(
            message,
            attack_label=attack_label,
        )

    def detect_attack(self, message: can.Message) -> str:
        """
        Detect known suspicious CAN traffic.

        Returns:
            Attack label or 'Normal'.
        """

        if (
            message.arbitration_id == self.SPEED_CAN_ID
            and message.dlc >= 1
            and message.data[0] >= self.FAKE_SPEED_THRESHOLD
        ):
            return "Fake Speed Attack"

        return "Normal"
