from src.simulation.base_ecu import BaseECU
from src.utils.constants import DOOR_ECU_ID
from src.utils.helpers import generate_door_status


class DoorECU(BaseECU):
    """
    Simulates the vehicle Door ECU.

    CAN ID:
        0x500

    Data:
        Byte 0: Door status.
            0 = Closed
            1 = Open

        Remaining bytes: Reserved.
    """

    def __init__(self):
        super().__init__(
            ecu_name="Door ECU",
            can_id=DOOR_ECU_ID,
            interval=2.0,
        )

    def generate_data(self) -> list[int]:
        """Generate a realistic door status CAN payload."""

        door_status = generate_door_status()

        return [
            door_status,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ]
