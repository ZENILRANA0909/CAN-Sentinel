import threading
import time
from abc import ABC, abstractmethod

from src.networking.can_interface import CANInterface


class BaseECU(threading.Thread, ABC):
    """
    Base ECU Class.
    """

    def __init__(
        self,
        ecu_name: str,
        can_id: int,
        interval: float = 1.0,
    ):
        super().__init__(daemon=True)

        self.ecu_name = ecu_name
        self.can_id = can_id
        self.interval = interval

        self.bus = CANInterface()

        self.running = False

    def start_ecu(self):
        self.running = True
        self.start()

    def stop_ecu(self):
        self.running = False

    def run(self):
        while self.running:

            data = self.generate_data()

            self.bus.send(
                arbitration_id=self.can_id,
                data=data,
            )

            print(
                f"{self.ecu_name} -> "
                f"ID={hex(self.can_id)} "
                f"DATA={data}"
            )

            time.sleep(self.interval)

    @abstractmethod
    def generate_data(self):
        pass