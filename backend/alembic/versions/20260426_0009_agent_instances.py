"""agent_instances: per-process bot identity + heartbeat

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_instances",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("hostname", sa.String(), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("sdk_version", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_heartbeat_at", sa.DateTime(timezone=True), nullable=False
        ),
    )
    op.create_index(
        "idx_agent_instances_ws_agent",
        "agent_instances",
        ["workspace_id", "agent_name", sa.text("last_heartbeat_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_agent_instances_ws_agent", table_name="agent_instances")
    op.drop_table("agent_instances")
