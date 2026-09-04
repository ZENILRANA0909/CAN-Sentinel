"""Configuration, logging, error handling and the message pipeline."""

from __future__ import annotations

import json
import logging

import pytest

from app.can.signals import encode_vehicle_speed
from app.core.config import Settings, parse_can_id
from app.core.exceptions import (
    CanInterfaceError,
    CanSentinelError,
    ConfigurationError,
    InvalidCanMessageError,
    MonitorError,
    ResourceNotFoundError,
    SimulationError,
    StorageError,
)
from app.core.logging import ConsoleFormatter, JsonFormatter, configure_logging, get_logger
from app.core.runtime_config import ConfigService, DetectionConfig, RuntimeConfig
from app.services.pipeline import MessagePipeline
from tests.conftest import make_message


class TestSettings:
    def test_defaults_are_usable_without_any_environment(self) -> None:
        settings = Settings()
        assert settings.app_env == "development"
        assert settings.can_interface == "virtual"
        assert settings.flood_threshold > 0

    def test_csv_fields_are_parsed(self) -> None:
        settings = Settings(cors_origins="http://a.test, http://b.test ,")
        assert settings.cors_origin_list == ["http://a.test", "http://b.test"]

    def test_allowlist_accepts_hex_and_decimal(self) -> None:
        settings = Settings(allowed_can_ids="0x100, 512,0x300")
        assert settings.allowed_can_id_set == {0x100, 512, 0x300}

    def test_log_level_is_normalised(self) -> None:
        assert Settings(log_level="debug").log_level == "DEBUG"

    def test_invalid_log_level_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            Settings(log_level="chatty")

    @pytest.mark.parametrize(("raw", "expected"), [("0x300", 768), ("768", 768), (768, 768), ("0X7FF", 2047)])
    def test_can_id_parsing(self, raw: str | int, expected: int) -> None:
        assert parse_can_id(raw) == expected

    @pytest.mark.parametrize("raw", ["", "  ", "zzz", "0xZZ"])
    def test_bad_can_id_is_rejected(self, raw: str) -> None:
        with pytest.raises(ValueError):
            parse_can_id(raw)

    def test_relative_sqlite_path_is_anchored_to_the_project(self) -> None:
        settings = Settings(database_url="sqlite:///./data/test.db")
        assert settings.sqlite_path is not None
        assert settings.sqlite_path.is_absolute()
        assert settings.resolved_database_url.startswith("sqlite:///")
        assert "./data" not in settings.resolved_database_url

    def test_memory_database_has_no_path(self) -> None:
        settings = Settings(database_url="sqlite:///:memory:")
        assert settings.sqlite_path is None
        assert settings.resolved_database_url == "sqlite:///:memory:"

    def test_non_sqlite_url_is_left_alone(self) -> None:
        settings = Settings(database_url="postgresql://u:p@host/db")
        assert settings.sqlite_path is None
        assert settings.resolved_database_url == "postgresql://u:p@host/db"

    def test_out_of_range_values_are_rejected(self) -> None:
        with pytest.raises(ValueError):
            Settings(flood_threshold=0)
        with pytest.raises(ValueError):
            Settings(flood_suspicious_ratio=2.0)


class TestRuntimeConfig:
    def test_seeded_from_settings(self, config_service: ConfigService) -> None:
        detection = config_service.detection
        assert detection.flood_threshold == Settings().flood_threshold
        assert 0x300 in detection.allowed_can_id_set

    def test_suspicious_threshold_is_derived(self) -> None:
        config = DetectionConfig(flood_threshold=600.0, flood_suspicious_ratio=0.5)
        assert config.flood_suspicious_threshold == 300.0

    def test_partial_update_leaves_other_fields_alone(self, config_service: ConfigService) -> None:
        before = config_service.detection.flood_threshold
        _, changed = config_service.update({"detection": {"fake_speed_threshold": 150.0}})
        assert changed == ["detection.fake_speed_threshold"]
        assert config_service.detection.flood_threshold == before

    def test_update_bumps_the_revision(self, config_service: ConfigService) -> None:
        before = config_service.revision
        config_service.update({"detection": {"fake_speed_threshold": 150.0}})
        assert config_service.revision == before + 1

    def test_invalid_update_is_atomic(self, config_service: ConfigService) -> None:
        before = config_service.current.model_dump()
        with pytest.raises(ConfigurationError):
            config_service.update({"detection": {"flood_threshold": -1}})
        assert config_service.current.model_dump() == before

    def test_cross_field_rule_is_enforced(self, config_service: ConfigService) -> None:
        with pytest.raises(ConfigurationError, match="fake_speed_suspicious_threshold"):
            config_service.update({"detection": {"fake_speed_suspicious_threshold": 900.0}})

    def test_per_id_threshold_cannot_exceed_the_global_one(
        self, config_service: ConfigService
    ) -> None:
        with pytest.raises(ConfigurationError, match="per_id_flood_threshold"):
            config_service.update({"detection": {"per_id_flood_threshold": 99_999.0}})

    def test_reset_restores_the_seeded_values(self, config_service: ConfigService) -> None:
        original = config_service.detection.fake_speed_threshold
        # Must stay at or above the suspicious threshold, or the update is rejected.
        config_service.update({"detection": {"fake_speed_threshold": 333.0}})
        config_service.reset()
        assert config_service.detection.fake_speed_threshold == original

    def test_listeners_are_notified(self, config_service: ConfigService) -> None:
        seen: list[RuntimeConfig] = []
        config_service.subscribe(seen.append)
        config_service.update({"detection": {"fake_speed_threshold": 150.0}})
        assert len(seen) == 1

    def test_a_failing_listener_does_not_break_the_update(
        self, config_service: ConfigService
    ) -> None:
        config_service.subscribe(lambda _config: (_ for _ in ()).throw(RuntimeError("boom")))
        config_service.update({"detection": {"fake_speed_threshold": 150.0}})
        assert config_service.detection.fake_speed_threshold == 150.0

    def test_restart_required_fields_are_identified(self) -> None:
        assert ConfigService.restart_required(["can.channel", "detection.flood_threshold"]) == [
            "can.channel"
        ]

    def test_allowlist_accepts_mixed_notations(self) -> None:
        config = DetectionConfig(allowed_can_ids=["0x100", 512, "0x300"])
        # Normalised to integers, de-duplicated and sorted.
        assert config.allowed_can_ids == [0x100, 512, 0x300]

    def test_unknown_field_is_rejected(self, config_service: ConfigService) -> None:
        with pytest.raises(ConfigurationError):
            config_service.update({"detection": {"not_a_field": 1}})


class TestLogging:
    def test_json_formatter_emits_one_line_of_json(self) -> None:
        record = logging.LogRecord("t", logging.INFO, "f", 1, "hello", (), None)
        record.context = {"can_id": "0x300"}  # type: ignore[attr-defined]
        payload = json.loads(JsonFormatter().format(record))
        assert payload["message"] == "hello"
        assert payload["level"] == "INFO"
        assert payload["context"]["can_id"] == "0x300"

    def test_json_formatter_serialises_exceptions(self) -> None:
        try:
            raise ValueError("bang")
        except ValueError:
            import sys

            record = logging.LogRecord("t", logging.ERROR, "f", 1, "failed", (), sys.exc_info())
        payload = json.loads(JsonFormatter().format(record))
        assert "ValueError: bang" in payload["exception"]

    def test_console_formatter_appends_context(self) -> None:
        record = logging.LogRecord("t", logging.INFO, "f", 1, "hello", (), None)
        record.context = {"rate": 42}  # type: ignore[attr-defined]
        assert "rate=42" in ConsoleFormatter().format(record)

    def test_configure_logging_installs_a_console_handler(self, tmp_path) -> None:
        configure_logging(level="INFO", log_dir=tmp_path, to_file=True, force=True)
        root = logging.getLogger()
        assert root.handlers
        assert root.level == logging.INFO
        logger = get_logger("test.module")
        logger.info("hello", extra={"context": {"a": 1}})
        assert (tmp_path / "can-sentinel.log").exists()
        configure_logging(level="CRITICAL", to_file=False, force=True)

    def test_logger_namespace_is_stable(self) -> None:
        assert get_logger("can.interface").name == "can_sentinel.can.interface"
        assert get_logger("can_sentinel.already").name == "can_sentinel.already"


class TestExceptions:
    @pytest.mark.parametrize(
        ("error", "status"),
        [
            (CanSentinelError("x"), 500),
            (InvalidCanMessageError("x"), 422),
            (ConfigurationError("x"), 400),
            (CanInterfaceError("x"), 503),
            (SimulationError("x"), 409),
            (MonitorError("x"), 409),
            (StorageError("x"), 503),
            (ResourceNotFoundError("x"), 404),
        ],
    )
    def test_status_codes(self, error: CanSentinelError, status: int) -> None:
        assert error.status_code == status

    def test_payload_shape(self) -> None:
        error = InvalidCanMessageError("bad frame", details={"field": "arbitration_id"})
        assert error.to_payload() == {
            "error": "invalid_can_message",
            "message": "bad frame",
            "details": {"field": "arbitration_id"},
        }


class TestPipelineValidation:
    def test_accepts_a_valid_frame(self) -> None:
        message = MessagePipeline.validate({"arbitration_id": 0x300, "data": "DEADBEEF"})
        assert message.arbitration_id == 0x300
        assert message.data_hex == "DEADBEEF"

    def test_rejects_an_out_of_range_identifier_with_detail(self) -> None:
        with pytest.raises(InvalidCanMessageError) as caught:
            MessagePipeline.validate({"arbitration_id": 0x800})
        assert caught.value.details["errors"]

    def test_rejects_an_oversized_payload(self) -> None:
        with pytest.raises(InvalidCanMessageError):
            MessagePipeline.validate({"arbitration_id": 0x100, "data": "00" * 9})

    def test_rejects_a_malformed_payload(self) -> None:
        with pytest.raises(InvalidCanMessageError):
            MessagePipeline.validate({"arbitration_id": 0x100, "data": "ZZ"})

    async def test_history_filters(self, app_state) -> None:
        pipeline = app_state.pipeline
        # The speed frame carries a realistic value: an arbitrary payload here
        # would decode to a wild speed and be flagged, which is not what this
        # test is about.
        await pipeline.process_batch(
            [
                make_message(can_id=0x100, timestamp=1000.0, data=b"\xaa\xbb"),
                make_message(can_id=0x300, timestamp=1001.0, data=encode_vehicle_speed(60.0)),
            ]
        )
        assert len(pipeline.recent_messages(limit=10)) == 2
        assert len(pipeline.recent_messages(limit=10, can_id=0x300)) == 1
        assert len(pipeline.recent_messages(limit=10, search="AABB")) == 1
        assert len(pipeline.recent_messages(limit=10, search="0x300")) == 1
        assert pipeline.recent_messages(limit=10, flagged_only=True) == []

    async def test_history_is_bounded(self, app_state) -> None:
        pipeline = app_state.pipeline
        capacity = pipeline.status()["history_capacity"]
        await pipeline.process_batch(
            [make_message(timestamp=1000.0 + index * 0.01) for index in range(capacity + 50)]
        )
        assert pipeline.status()["history_size"] == capacity

    async def test_empty_batch_is_a_no_op(self, app_state) -> None:
        result = await app_state.pipeline.process_batch([])
        assert result.processed == 0

    async def test_clear_history(self, app_state) -> None:
        await app_state.pipeline.process_batch([make_message()])
        app_state.pipeline.clear_history()
        assert app_state.pipeline.recent_messages() == []
