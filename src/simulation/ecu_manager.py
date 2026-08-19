import logging

from src.simulation.base_ecu import BaseECU
from src.simulation.engine_ecu import EngineECU
from src.simulation.brake_ecu import BrakeECU
from src.simulation.speed_ecu import SpeedECU
from src.simulation.steering_ecu import SteeringECU
from src.simulation.door_ecu import DoorECU


logger = logging.getLogger(__name__)


class ECUManager:
    """
    Manages all simulated vehicle ECUs.

    The manager is responsible for:
    - Creating ECUs
    - Starting ECUs
    - Stopping ECUs
    - Reporting ECU status
    """

    def __init__(self):
        self.ecus: list[BaseECU] = [
            EngineECU(),
            BrakeECU(),
            SpeedECU(),
            SteeringECU(),
            DoorECU(),
        ]

    def start_all(self) -> None:
        """Start all ECU simulation threads."""

        logger.info("Starting all ECUs...")

        for ecu in self.ecus:
            if not ecu.is_alive():
                ecu.start_ecu()

        logger.info("All ECUs started.")

    def stop_all(self) -> None:
        """Stop all ECU simulation threads."""

        logger.info("Stopping all ECUs...")

        for ecu in self.ecus:
            ecu.stop_ecu()

        logger.info("All ECUs stopped.")

    def get_status(self) -> dict[str, str]:
        """
        Return the current status of every ECU.
        """

        status = {}

        for ecu in self.ecus:
            status[ecu.ecu_name] = (
                "Running" if ecu.running else "Stopped"
            )

        return status
