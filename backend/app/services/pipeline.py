"""The message pipeline.

Every frame that enters CAN-Sentinel travels this path exactly once:

``validate -> normalise -> statistics -> detection -> persist -> broadcast``

The pipeline is batch-oriented.  The receiver hands it everything the interface
had buffered, and each stage runs over the whole batch, which keeps the cost
per frame low enough to stay ahead of a flood.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from app.can.message import CanMessage
from app.can.signals import decode_frame, describe_can_id
from app.core.exceptions import InvalidCanMessageError
from app.core.logging import get_logger
from app.core.runtime_config import ConfigService
from app.detection.engine import DetectionEngine
from app.models.can_message import CanMessageRecord
from app.models.security_event import SecurityEventRecord
from app.services.broadcaster import Broadcaster, EventType
from app.services.statistics import TrafficStatistics
from app.storage.writer import PersistenceWriter

logger = get_logger("services.pipeline")


@dataclass
class PipelineResult:
    """What one batch produced."""

    processed: int = 0
    flagged: int = 0
    events: int = 0
    persisted: int = 0
    rejected: int = 0


class MessagePipeline:
    """Wires detection, statistics, persistence and streaming together."""

    def __init__(
        self,
        *,
        engine: DetectionEngine,
        statistics: TrafficStatistics,
        writer: PersistenceWriter,
        broadcaster: Broadcaster,
        config_service: ConfigService,
        history_size: int = 2000,
    ) -> None:
        self._engine = engine
        self._stats = statistics
        self._writer = writer
        self._broadcaster = broadcaster
        self._config = config_service
        self._history: deque[dict[str, Any]] = deque(maxlen=max(100, history_size))
        self._events: deque[dict[str, Any]] = deque(maxlen=500)
        self._processed = 0
        self._rejected = 0

    # ------------------------------------------------------------------ #
    # Ingest                                                             #
    # ------------------------------------------------------------------ #
    @staticmethod
    def validate(payload: dict[str, Any]) -> CanMessage:
        """Turn an untrusted dict into a validated frame.

        Used by the frame-injection endpoint. A bad frame is rejected here with
        a precise reason rather than being allowed to reach the detectors.
        """
        try:
            return CanMessage.model_validate(payload)
        except PydanticValidationError as exc:
            errors = [
                {"field": ".".join(str(part) for part in err["loc"]), "error": err["msg"]}
                for err in exc.errors()
            ]
            raise InvalidCanMessageError(
                "the supplied CAN frame is not valid", details={"errors": errors}
            ) from exc

    async def process_batch(self, messages: list[CanMessage]) -> PipelineResult:
        """Run the full pipeline over a batch of frames."""
        result = PipelineResult()
        if not messages:
            return result

        persist = self._config.current.retention.persist_can_messages
        message_rows: list[dict[str, Any]] = []
        event_rows: list[dict[str, Any]] = []
        wire_messages: list[dict[str, Any]] = []
        alerts: list[dict[str, Any]] = []

        for message in messages:
            outcome = self._engine.analyze(message)
            self._stats.record(message, outcome)

            flagged = outcome.detected
            wire = message.to_wire()
            wire["flagged"] = flagged
            wire["threat_level"] = outcome.threat_level.value
            wire["severity"] = outcome.severity.value
            wire["label"] = describe_can_id(message.arbitration_id)
            wire["decoded"] = decode_frame(message.arbitration_id, message.data)
            if flagged:
                wire["attack_types"] = sorted({a.value for a in outcome.attack_types})
                result.flagged += 1

            self._history.append(wire)
            wire_messages.append(wire)

            if persist:
                message_rows.append(CanMessageRecord.row_from_message(message, flagged=flagged))

            for detection in outcome.reportable:
                event_rows.append(
                    SecurityEventRecord.row_from_result(detection, channel=message.channel)
                )
                alert = detection.to_wire()
                alert["label"] = describe_can_id(message.arbitration_id)
                alerts.append(alert)
                self._events.appendleft(alert)
                result.events += 1

            result.processed += 1

        self._processed += result.processed

        # --- Persist (bounded queue, never blocks) ------------------------
        if message_rows:
            result.persisted = self._writer.submit_messages(message_rows)
        if event_rows:
            self._writer.submit_security_events(event_rows)

        # --- Stream ------------------------------------------------------
        self._broadcaster.queue_messages(wire_messages)
        for alert in alerts:
            self._broadcaster.publish(EventType.ATTACK_DETECTED, alert)
            logger.warning(
                "Security event",
                extra={
                    "context": {
                        "attack_type": alert["attack_type"],
                        "severity": alert["severity"],
                        "can_id": alert.get("can_id_hex"),
                        "detector": alert["detector"],
                        "confidence": alert["confidence"],
                    }
                },
            )
        return result

    def reject(self, reason: str) -> None:
        """Record a frame that failed validation before entering the pipeline."""
        self._rejected += 1
        self._stats.record_invalid()
        logger.warning("Rejected invalid CAN frame", extra={"context": {"reason": reason}})

    # ------------------------------------------------------------------ #
    # Live views                                                         #
    # ------------------------------------------------------------------ #
    def recent_messages(
        self,
        limit: int = 100,
        *,
        can_id: int | None = None,
        flagged_only: bool = False,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        """Newest-first slice of the in-memory ring buffer.

        Served from memory rather than the database so the live view is current
        even before the batching writer has committed.
        """
        items = reversed(self._history)
        needle = search.upper() if search else None
        out: list[dict[str, Any]] = []
        for item in items:
            if can_id is not None and item["can_id"] != can_id:
                continue
            if flagged_only and not item.get("flagged"):
                continue
            if needle and needle not in item["data"] and needle not in item["can_id_hex"].upper():
                continue
            out.append(item)
            if len(out) >= max(1, limit):
                break
        return out

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._events)[: max(1, limit)]

    def clear_history(self) -> None:
        self._history.clear()
        self._events.clear()

    def status(self) -> dict[str, Any]:
        return {
            "processed": self._processed,
            "rejected": self._rejected,
            "history_size": len(self._history),
            "history_capacity": self._history.maxlen,
            "recent_events": len(self._events),
            "persist_can_messages": self._config.current.retention.persist_can_messages,
        }
