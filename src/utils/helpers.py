import random


def generate_engine_rpm() -> int:
    """Generate a realistic engine RPM."""
    return random.randint(800, 5000)


def generate_speed() -> int:
    """Generate a realistic vehicle speed."""
    return random.randint(0, 180)


def generate_brake_pressure() -> int:
    """Generate brake pressure."""
    return random.randint(0, 100)


def generate_steering_angle() -> int:
    """Generate steering angle."""
    return random.randint(-45, 45)


def generate_door_status() -> int:
    """
    0 = Closed
    1 = Open
    """
    return random.choice([0, 1])