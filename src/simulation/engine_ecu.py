from src.simulation.base_ecu import BaseECU

from src.utils.constants import ENGINE_ECU_ID

from src.utils.helpers import (
    generate_engine_rpm,
    generate_speed,
)


class EngineECU(BaseECU):

    def __init__(self):
        super().__init__(
            ecu_name="Engine ECU",
            can_id=ENGINE_ECU_ID,
            interval=1,
        )

    def generate_data(self):

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