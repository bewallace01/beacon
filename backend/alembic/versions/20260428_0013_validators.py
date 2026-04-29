"""validators: workspace-scoped validator configs + per-event validation results

Phase 7.3 of the output-validation rollout. Two new tables:

  validator_configs   workspace_id + event_kind + validator_name → JSON config.
                      The workspace's "what should be validated, by whom" map.
  event_validations   one row per (event, validator) pair, recording the
                      pass/fail/warn status and the violations JSON.

event_validations rows are written synchronously by the POST /events handler
after the event is inserted. The pipeline is advisory in 7A: failures don't
block ingestion.

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "validator_configs",
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "event_kind", sa.String(length=64), primary_key=True, nullable=False
        ),
        sa.Column(
            "validator_name", sa.String(length=64), primary_key=True, nullable=False
        ),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Hot path lookup at /events ingestion: "give me all validators for
    # this workspace + event_kind". Composite PK already covers it, but
    # explicit index makes intent obvious.
    op.create_index(
        "idx_validator_configs_ws_kind",
        "validator_configs",
        ["workspace_id", "event_kind"],
    )

    op.create_table(
        "event_validations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "event_id",
            sa.BigInteger(),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("validator_name", sa.String(length=64), nullable=False),
        # 'pass' | 'fail' | 'warn'. Kept as a string rather than an enum so
        # adding a new status (e.g. 'timeout', 'error') doesn't need a
        # follow-up migration.
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("violations", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "event_id", "validator_name", name="uq_event_validations_event_validator"
        ),
    )
    op.create_index(
        "idx_event_validations_event_id", "event_validations", ["event_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_event_validations_event_id", table_name="event_validations")
    op.drop_table("event_validations")
    op.drop_index("idx_validator_configs_ws_kind", table_name="validator_configs")
    op.drop_table("validator_configs")
