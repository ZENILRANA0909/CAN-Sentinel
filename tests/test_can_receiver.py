import time

from src.networking.can_interface import CANInterface
from src.networking.can_receiver import CANReceiver


def test_can_receiver_receives_message():
    bus = CANInterface()

    received_messages = []

    def callback(message):
        received_messages.append(message)

    receiver = CANReceiver(
        bus=bus,
        callback=callback,
    )

    try:
        receiver.start()

        bus.send(
            arbitration_id=0x123,
            data=[1, 2, 3, 4],
        )

        deadline = time.time() + 2.0

        while not received_messages and time.time() < deadline:
            time.sleep(0.01)

        assert len(received_messages) == 1

        message = received_messages[0]

        assert message.arbitration_id == 0x123
        assert message.dlc == 4
        assert list(message.data) == [1, 2, 3, 4]

    finally:
        receiver.stop()
        bus.shutdown()
