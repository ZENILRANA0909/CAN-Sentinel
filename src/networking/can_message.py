from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass
class CANMessage:
    """
    Represents a CAN packet inside the application.
    """

    timestamp: datetime = field(default_factory=datetime.now)
    can_id: int = 0x000
    data: List[int] = field(default_factory=lambda: [0] * 8)
    is_extended_id: bool = False
    attack_label: str = "Normal"

    @property
    def dlc(self) -> int:
        """Return Data Length Code."""
        return len(self.data)

    def to_dict(self) -> dict:
        """Convert message to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "can_id": hex(self.can_id),
            "dlc": self.dlc,
            "data": self.data,
            "attack_label": self.attack_label,
        }

    def __str__(self) -> str:
        return (
            f"[{self.timestamp.strftime('%H:%M:%S')}] "
            f"ID={hex(self.can_id)} "
            f"DLC={self.dlc} "
            f"DATA={self.data} "
            f"LABEL={self.attack_label}"
        )