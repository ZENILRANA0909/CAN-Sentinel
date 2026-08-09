import can

from config.settings import CAN_INTERFACE, CAN_CHANNEL


class CANInterface:
    """
    Central CAN Bus Interface.
    """

    def __init__(self):
        if CAN_CHANNEL:
            self.bus = can.Bus(
                interface=CAN_INTERFACE,
                channel=CAN_CHANNEL,
            )
        else:
            self.bus = can.Bus(interface=CAN_INTERFACE)

        print("CAN Interface Initialized")

    def send(self, arbitration_id: int, data: list[int]):
        """
        Send a CAN frame.
        """

        message = can.Message(
            arbitration_id=arbitration_id,
            data=data,
            is_extended_id=False,
        )

        self.bus.send(message)

    def receive(self, timeout=1.0):
        return self.bus.recv(timeout)