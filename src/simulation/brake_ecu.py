from src.networking.can_interface import CANInterface
from src.simulation.base_ecu import BaseECU
from src.utils.constants import BRAKE_ECU_ID
from src.utils.helpers import generate_brake_pressure


class BrakeECU(BaseECU):
    """
    Simulates the vehicle Brake ECU.

    CAN ID:
        0x200

    Data:
        Byte 0: Brake pressure (0-100)
        Byte 1: ABS status
        Remaining bytes: Reserved
    """

    def __init__(self, bus: CANInterface):
        super().__init__(
            ecu_name="Brake ECU",
            can_id=BRAKE_ECU_ID,
            bus=bus,
            interval=1.0,
        )

    def generate_data(self) -> list[int]:
        """Generate a realistic brake CAN payload."""

        brake_pressure = generate_brake_pressure()

        # ABS activates at high brake pressure.
        abs_status = 1 if brake_pressure >= 80 else 0

        return [
            brake_pressure,
            abs_status,
            0,
            0,
            0,
            0,
            0,
            0,
        ]
