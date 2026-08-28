import time

from src.networking.can_system import CANSystem


def test_can_system_start_and_stop():
    system = CANSystem()

    system.start()

    try:
        time.sleep(0.5)

        status = system.get_ecu_status()

        assert len(status) == 5
        assert all(state == "Running" for state in status.values())

    finally:
        system.stop()

        status = system.get_ecu_status()

        assert all(state == "Stopped" for state in status.values())

