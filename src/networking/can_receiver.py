import logging
import threading
from collections.abc import Callable

import can

from src.networking.can_interface import CANInterface


logger = logging.getLogger(__name__)


class CANReceiver:
    """
    Continuously receives CAN messages from the shared CAN bus.

    A callback can be registered to process every received message.
    """

    def __init__(
        self,
        bus: CANInterface,
        callback: Callable[[can.Message], None] | None = None,
    ):
        self.bus = bus
        self.callback = callback

        self.running = False
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the CAN receiver thread."""

        if self.running:
            logger.warning("CAN receiver is already running.")
            return

        self.running = True

        self.thread = threading.Thread(
            target=self._receive_loop,
            name="CANReceiver",
            daemon=True,
        )

        self.thread.start()

        logger.info("CAN receiver started.")

    def stop(self) -> None:
        """Stop the CAN receiver thread."""

        self.running = False

        if self.thread is not None:
            self.thread.join(timeout=2.0)

        logger.info("CAN receiver stopped.")

    def _receive_loop(self) -> None:
        """Continuously receive CAN frames."""

        while self.running:
            try:
                message = self.bus.receive(timeout=0.5)

                if message is None:
                    continue

                logger.info(
                    "RX CAN ID=%s DLC=%d DATA=%s",
                    hex(message.arbitration_id),
                    message.dlc,
                    list(message.data),
                )

                if self.callback is not None:
                    self.callback(message)

            except Exception:
                logger.exception("Error receiving CAN message.")
