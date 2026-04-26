"""multi-tenancy: workspaces + workspace_id on every row

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-25

Adds a workspaces table and a workspace_id column to runs, events, and
agents. Existing rows (if any) backfill to a seeded "default" workspace so
the spine demo keeps working unchanged. Agent PK becomes composite
(workspace_id, name) so different workspaces can have agents with the same
name.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # 1. workspaces table
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("api_key", sa.String(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 2. seed default workspace
    op.execute(
        f"""
        INSERT INTO workspaces (id, name, api_key, created_at)
        VALUES (
            '{DEFAULT_WORKSPACE_ID}',
            'Default',
            'demo-key',
            now()
        )
        """
    )

    # 3. add workspace_id to runs, events, agents (nullable for backfill)
    for table in ("runs", "events", "agents"):
        op.add_column(table, sa.Column("workspace_id", sa.String(), nullable=True))
        op.execute(
            f"UPDATE {table} SET workspace_id = '{DEFAULT_WORKSPACE_ID}' "
            f"WHERE workspace_id IS NULL"
        )
        op.alter_column(table, "workspace_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_workspace",
            table,
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # 4. agents PK: drop the name-only PK, recreate as (workspace_id, name)
    op.drop_constraint("agents_pkey", "agents", type_="primary")
    op.create_primary_key("agents_pkey", "agents", ["workspace_id", "name"])

    # 5. workspace-aware indexes (the cost rollup hot path is now scoped)
    op.create_index(
        "idx_events_ws_agent_kind_ts",
        "events",
        ["workspace_id", "agent_name", "kind", "timestamp"],
    )
    op.create_index(
        "idx_runs_ws_started_at",
        "runs",
        ["workspace_id", sa.text("started_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_runs_ws_started_at", table_name="runs")
    op.drop_index("idx_events_ws_agent_kind_ts", table_name="events")
    op.drop_constraint("agents_pkey", "agents", type_="primary")
    op.create_primary_key("agents_pkey", "agents", ["name"])
    for table in ("agents", "events", "runs"):
        op.drop_constraint(f"fk_{table}_workspace", table, type_="foreignkey")
        op.drop_column(table, "workspace_id")
    op.drop_table("workspaces")
