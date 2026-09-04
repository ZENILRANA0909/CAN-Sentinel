"""Initial schema: CAN messages, security events and system events.

Revision ID: 0001
Revises:
Create Date: 2025-01-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "can_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.Float(), nullable=False),
        sa.Column("can_id", sa.Integer(), nullable=False),
        sa.Column("can_id_hex", sa.String(length=12), nullable=False),
        sa.Column("is_extended_id", sa.Boolean(), nullable=False),
        sa.Column("dlc", sa.Integer(), nullable=False),
        sa.Column("data", sa.String(length=128), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("message_type", sa.String(length=8), nullable=False),
        sa.Column("flagged", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_can_messages")),
    )
    op.create_index(op.f("ix_can_messages_timestamp"), "can_messages", ["timestamp"])
    op.create_index(op.f("ix_can_messages_can_id"), "can_messages", ["can_id"])
    op.create_index(op.f("ix_can_messages_flagged"), "can_messages", ["flagged"])
    op.create_index("ix_can_messages_ts_id", "can_messages", ["timestamp", "can_id"])
    op.create_index("ix_can_messages_id_ts", "can_messages", ["can_id", "timestamp"])

    op.create_table(
        "security_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.Float(), nullable=False),
        sa.Column("attack_type", sa.String(length=32), nullable=False),
        sa.Column("threat_level", sa.String(length=16), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("detector", sa.String(length=48), nullable=False),
        sa.Column("can_id", sa.Integer(), nullable=True),
        sa.Column("can_id_hex", sa.String(length=12), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_events")),
    )
    op.create_index(op.f("ix_security_events_timestamp"), "security_events", ["timestamp"])
    op.create_index(op.f("ix_security_events_attack_type"), "security_events", ["attack_type"])
    op.create_index(op.f("ix_security_events_severity"), "security_events", ["severity"])
    op.create_index(op.f("ix_security_events_detector"), "security_events", ["detector"])
    op.create_index(op.f("ix_security_events_can_id"), "security_events", ["can_id"])
    op.create_index(op.f("ix_security_events_status"), "security_events", ["status"])
    op.create_index("ix_security_events_ts_sev", "security_events", ["timestamp", "severity"])
    op.create_index("ix_security_events_type_ts", "security_events", ["attack_type", "timestamp"])

    op.create_table(
        "system_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.Float(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_events")),
    )
    op.create_index(op.f("ix_system_events_timestamp"), "system_events", ["timestamp"])
    op.create_index(op.f("ix_system_events_event_type"), "system_events", ["event_type"])
    op.create_index(op.f("ix_system_events_severity"), "system_events", ["severity"])


def downgrade() -> None:
    op.drop_table("system_events")
    op.drop_table("security_events")
    op.drop_table("can_messages")
