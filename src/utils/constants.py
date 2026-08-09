"""
Common constants used throughout the project.
"""

# ==========================
# CAN IDs
# ==========================

ENGINE_ECU_ID = 0x100
BRAKE_ECU_ID = 0x200
SPEED_ECU_ID = 0x300
STEERING_ECU_ID = 0x400
DOOR_ECU_ID = 0x500


# ==========================
# ECU Names
# ==========================

ENGINE = "Engine ECU"
BRAKE = "Brake ECU"
SPEED = "Speed ECU"
STEERING = "Steering ECU"
DOOR = "Door ECU"


# ==========================
# Attack Types
# ==========================

NORMAL = "Normal"

FAKE_SPEED = "Fake Speed"

FAKE_BRAKE = "Fake Brake"

FLOOD_ATTACK = "Flood Attack"

REPLAY_ATTACK = "Replay Attack"

SPOOF_ATTACK = "Spoofed ECU"

RANDOM_INJECTION = "Random Injection"

BUS_SATURATION = "Bus Saturation"