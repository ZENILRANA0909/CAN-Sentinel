import logging

from src.networking.can_interface import CANInterface
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

    A single CANInterface is shared by every ECU so that all
    ECUs communicate through the same virtual CAN bus.
    """

    def __init__(self):
        # Create ONE shared CAN interface.
        self.bus = CANInterface()

        # Pass the same bus to every ECU.
        self.ecus: list[BaseECU] = [
            EngineECU(self.bus),
            BrakeECU(self.bus),
            SpeedECU(self.bus),
            SteeringECU(self.bus),
            DoorECU(self.bus),
        ]

    def start_all(self) -> None:
        """Start all ECU simulation threads."""

        logger.info("Starting all ECUs...")

        for ecu in self.ecus:
            ecu.start_ecu()

        logger.info("All ECUs started.")

    def stop_all(self) -> None:
        """Stop all ECU simulation threads."""

        logger.info("Stopping all ECUs...")

        for ecu in self.ecus:
            ecu.stop_ecu()

        logger.info("All ECUs stopped.")

    def get_status(self) -> dict[str, str]:
        """Return the current status of every ECU."""

        return {
            ecu.ecu_name: (
                "Running" if ecu.running else "Stopped"
            )
            for ecu in self.ecus
        }

    def get_ecus(self) -> list[BaseECU]:
        """Return all managed ECUs."""

        return self.ecus
