from src.networking.can_interface import CANInterface
from src.simulation.base_ecu import BaseECU
from src.utils.constants import SPEED_ECU_ID
from src.utils.helpers import generate_speed


class SpeedECU(BaseECU):
    """
    Simulates the vehicle Speed ECU.

    CAN ID:
        0x300

    Data:
        Byte 0: Vehicle speed (0-180 km/h)
        Remaining bytes: Reserved
    """

    def __init__(self, bus: CANInterface):
        super().__init__(
            ecu_name="Speed ECU",
            can_id=SPEED_ECU_ID,
            bus=bus,
            interval=0.5,
        )

    def generate_data(self) -> list[int]:
        """Generate a realistic vehicle speed CAN payload."""

        speed = generate_speed()

        return [
            speed,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ]
