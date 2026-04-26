"""initial schema (runs, events, agents)

Revision ID: 0001
Revises:
Create Date: 2026-04-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_runs_started_at", "runs", [sa.text("started_at DESC")]
    )

    op.create_table(
        "events",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_events_run_id", "events", ["run_id"])
    op.create_index(
        "idx_events_agent_kind_ts",
        "events",
        ["agent_name", "kind", "timestamp"],
    )

    op.create_table(
        "agents",
        sa.Column("name", sa.String(), primary_key=True, nullable=False),
        sa.Column("daily_cost_cap_usd", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("agents")
    op.drop_index("idx_events_agent_kind_ts", table_name="events")
    op.drop_index("idx_events_run_id", table_name="events")
    op.drop_table("events")
    op.drop_index("idx_runs_started_at", table_name="runs")
    op.drop_table("runs")
