import logging

from src.attacks.fake_speed_attack import FakeSpeedAttack
from src.networking.can_interface import CANInterface


logger = logging.getLogger(__name__)


class AttackManager:
    """Manage CAN attack simulations."""

    def __init__(self, bus: CANInterface):
        self.bus = bus

        self.fake_speed_attack = FakeSpeedAttack(
            bus=self.bus,
            fake_speed=250,
            interval=0.2,
        )

    def start_fake_speed(self) -> None:
        """Start the fake speed attack."""

        logger.warning("Starting Fake Speed Attack.")
        self.fake_speed_attack.start()

    def stop_fake_speed(self) -> None:
        """Stop the fake speed attack."""

        logger.warning("Stopping Fake Speed Attack.")
        self.fake_speed_attack.stop()

    def stop_all(self) -> None:
        """Stop all active attacks."""

        self.fake_speed_attack.stop()
        logger.info("All attacks stopped.")
