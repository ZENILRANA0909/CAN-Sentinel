"""
Custom exceptions for CAN-Sentinel.
"""


class CANSentinelError(Exception):
    """Base exception for the application."""


class InvalidCANMessageError(CANSentinelError):
    """Raised when a CAN message is invalid."""


class CANInterfaceError(CANSentinelError):
    """Raised when CAN interface fails."""


class AttackSimulationError(CANSentinelError):
    """Raised when attack simulation fails."""