from src.networking.can_interface import CANInterface
from src.simulation.base_ecu import BaseECU
from src.utils.constants import STEERING_ECU_ID
from src.utils.helpers import generate_steering_angle


class SteeringECU(BaseECU):
    """
    Simulates the vehicle Steering ECU.

    CAN ID:
        0x400

    Data:
        Byte 0: Encoded steering angle.
        Remaining bytes: Reserved.

    Steering angle range:
        -45 to +45 degrees.
    """

    def __init__(self, bus: CANInterface):
        super().__init__(
            ecu_name="Steering ECU",
            can_id=STEERING_ECU_ID,
            bus=bus,
            interval=0.5,
        )

    def generate_data(self) -> list[int]:
        """Generate a realistic steering CAN payload."""

        angle = generate_steering_angle()

        # Convert -45..45 degrees to 0..90 for CAN transmission.
        encoded_angle = angle + 45

        return [
            encoded_angle,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ]
