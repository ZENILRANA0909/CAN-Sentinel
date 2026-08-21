from src.networking.can_interface import CANInterface
from src.simulation.base_ecu import BaseECU
from src.utils.constants import ENGINE_ECU_ID
from src.utils.helpers import generate_engine_rpm, generate_speed


class EngineECU(BaseECU):
    """
    Simulates the Engine ECU.

    CAN ID:
        0x100

    Data:
        Byte 0-1: Engine RPM
        Byte 2: Vehicle speed
        Remaining bytes: Reserved
    """

    def __init__(self, bus: CANInterface):
        super().__init__(
            ecu_name="Engine ECU",
            can_id=ENGINE_ECU_ID,
            bus=bus,
            interval=1.0,
        )

    def generate_data(self) -> list[int]:
        """Generate engine CAN payload."""

        rpm = generate_engine_rpm()
        speed = generate_speed()

        return [
            rpm >> 8,
            rpm & 0xFF,
            speed,
            0,
            0,
            0,
            0,
            0,
        ]
