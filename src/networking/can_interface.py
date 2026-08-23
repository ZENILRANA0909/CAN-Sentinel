import can

from config.settings import CAN_INTERFACE, CAN_CHANNEL


class CANInterface:
    """
    Central CAN bus interface.

    Supports the macOS python-can virtual backend and
    Linux SocketCAN.
    """

    def __init__(self):
        if CAN_INTERFACE == "virtual":
            self.bus = can.Bus(
                interface="virtual",
                receive_own_messages=True,
            )

        elif CAN_INTERFACE == "socketcan":
            if not CAN_CHANNEL:
                raise ValueError(
                    "CAN_CHANNEL must be configured for SocketCAN."
                )

            self.bus = can.Bus(
                interface="socketcan",
                channel=CAN_CHANNEL,
            )

        else:
            raise ValueError(
                f"Unsupported CAN interface: {CAN_INTERFACE}"
            )

        print("CAN Interface Initialized")

    def send(
        self,
        arbitration_id: int,
        data: list[int],
    ) -> None:
        """
        Send a standard CAN frame.
        """

        if not 0 <= arbitration_id <= 0x7FF:
            raise ValueError(
                f"Invalid standard CAN ID: {hex(arbitration_id)}"
            )

        if not 0 <= len(data) <= 8:
            raise ValueError(
                "CAN payload must contain between 0 and 8 bytes."
            )

        if any(not 0 <= byte <= 255 for byte in data):
            raise ValueError(
                "CAN data bytes must be between 0 and 255."
            )

        message = can.Message(
            arbitration_id=arbitration_id,
            data=data,
            is_extended_id=False,
        )

        self.bus.send(message)

    def receive(
        self,
        timeout: float = 1.0,
    ) -> can.Message | None:
        """
        Receive one CAN frame.

        Returns:
            A python-can Message or None if the timeout expires.
        """

        return self.bus.recv(timeout)

    def shutdown(self) -> None:
        """Safely shut down the CAN bus."""

        self.bus.shutdown()
