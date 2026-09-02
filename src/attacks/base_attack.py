import threading
from abc import ABC, abstractmethod

from src.networking.can_interface import CANInterface


class BaseAttack(ABC):
    """
    Base class for all CAN attack simulations.
    """

    def __init__(self, bus: CANInterface):
        self.bus = bus
        self.running = False
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the attack in a background thread."""

        if self.running:
            return

        self.running = True

        self.thread = threading.Thread(
            target=self.run,
            daemon=True,
        )

        self.thread.start()

    def stop(self) -> None:
        """Stop the attack."""

        self.running = False

        if self.thread is not None:
            self.thread.join(timeout=2.0)

    @abstractmethod
    def run(self) -> None:
        """Run the attack."""
        pass
