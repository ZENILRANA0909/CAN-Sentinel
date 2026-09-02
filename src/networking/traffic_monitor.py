from typing import Optional

from src.networking.can_receiver import CANReceiver
from src.logging.can_logger import CANLogger


class CANTrafficMonitor:
    """
    Monitors CAN traffic and detects suspicious traffic patterns.
    """

    def __init__(
        self,
        receiver: Optional[CANReceiver],
        logger_instance: CANLogger,
    ):
        self.receiver = receiver
        self.logger = logger_instance

        # Track repeated messages for CAN flood detection.
        self.flood_id = 0x555
        self.flood_count = 0
        self.flood_threshold = 20

        # Register callback only when a receiver is provided.
        if self.receiver is not None:
            self.receiver.callback = self.process_message

    def process_message(self, message):
        """
        Process a received CAN message and log the detection result.
        """
        detection = self.detect_attack(message)

        self.logger.log_message(
            message,
            detection,
        )

        return detection

    def detect_attack(self, message):
        """
        Detect known CAN attack patterns.

        Fake Speed Attack:
            CAN ID 0x300 with first data byte 0xFA.

        CAN Flood Attack:
            20 or more repeated messages using CAN ID 0x555.
        """

        arbitration_id = message.arbitration_id
        data = list(message.data)

        # Fake Speed Attack
        if (
            arbitration_id == 0x300
            and len(data) > 0
            and data[0] == 0xFA
        ):
            return "Fake Speed Attack"

        # CAN Flood Attack
        if arbitration_id == self.flood_id:
            self.flood_count += 1

            if self.flood_count >= self.flood_threshold:
                return "CAN Flood Attack"
        else:
            self.flood_count = 0

        # Normal traffic
        return "Normal"

    def start(self):
        """Start the CAN receiver if one is configured."""
        if self.receiver is not None:
            self.receiver.start()

    def stop(self):
        """Stop the CAN receiver if one is configured."""
        if self.receiver is not None:
            self.receiver.stop()
