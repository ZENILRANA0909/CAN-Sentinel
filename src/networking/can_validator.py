from src.networking.can_message import CANMessage


class CANValidator:
    """
    Validates CAN messages.
    """

    STANDARD_MAX_ID = 0x7FF
    EXTENDED_MAX_ID = 0x1FFFFFFF

    @staticmethod
    def validate(message: CANMessage) -> bool:
        """
        Validate CAN ID and payload.
        """

        if message.is_extended_id:
            if not (0 <= message.can_id <= CANValidator.EXTENDED_MAX_ID):
                return False
        else:
            if not (0 <= message.can_id <= CANValidator.STANDARD_MAX_ID):
                return False

        if len(message.data) > 8:
            return False

        for byte in message.data:
            if not (0 <= byte <= 255):
                return False

        return True