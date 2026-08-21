import logging
import threading
import time
from abc import ABC, abstractmethod

from src.networking.can_interface import CANInterface


logger = logging.getLogger(__name__)


class BaseECU(threading.Thread, ABC):
    """
    Base class for all simulated ECUs.

    Each ECU receives a shared CANInterface from the ECU manager.
    """

    def __init__(
        self,
        ecu_name: str,
        can_id: int,
        bus: CANInterface,
        interval: float = 1.0,
    ):
        super().__init__(daemon=True)

        self.ecu_name = ecu_name
        self.can_id = can_id
        self.bus = bus
        self.interval = interval

        self.running = False

    def start_ecu(self) -> None:
        """Start the ECU simulation thread."""

        if self.running:
            logger.warning("%s is already running.", self.ecu_name)
            return

        self.running = True
        self.start()

        logger.info("%s started.", self.ecu_name)

    def stop_ecu(self) -> None:
        """Stop the ECU simulation thread."""

        self.running = False

        logger.info("%s stopping.", self.ecu_name)

    def run(self) -> None:
        """Continuously generate and transmit CAN messages."""

        while self.running:

            try:
                data = self.generate_data()

                self.bus.send(
                    arbitration_id=self.can_id,
                    data=data,
                )

                logger.info(
                    "%s -> ID=%s DATA=%s",
                    self.ecu_name,
                    hex(self.can_id),
                    data,
                )

                time.sleep(self.interval)

            except Exception:
                logger.exception(
                    "Error while running %s.",
                    self.ecu_name,
                )

                self.running = False

    @abstractmethod
    def generate_data(self) -> list[int]:
        """
        Generate the CAN payload for this ECU.

        Returns:
            A list containing 0–8 CAN data bytes.
        """
        raise NotImplementedError
