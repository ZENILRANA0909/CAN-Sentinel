import time

from src.simulation.engine_ecu import EngineECU


def main():

    print("===== CAN Sentinel =====")

    engine = EngineECU()

    engine.start_ecu()

    try:

        while True:
            time.sleep(1)

    except KeyboardInterrupt:

        engine.stop_ecu()

        print("\nStopped.")


if __name__ == "__main__":
    main()