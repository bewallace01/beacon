"""notifications: workspace-scoped channels + per-delivery audit

Phase 9.1 of the notifications rollout. Two tables:

  notification_channels   one row per registered destination
                          (Slack/Discord/Teams/Mattermost/webhook).
                          Workspace-scoped, unique-by-name within
                          workspace.
  notification_deliveries one row per attempted send. Audit trail —
                          dashboard renders "3 sent, 0 failed in the
                          last 24h" and links to the per-delivery
                          response details.

The actual dispatcher (HTTP-out, formatters per channel type) lands in
Phase 9.2. 9.1 ships the schema + endpoints + URL masking + a stub for
the test-fire endpoint that writes a 'skipped' row.

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_channels",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=64), nullable=False),
        # 'slack' | 'discord' | 'teams' | 'mattermost' | 'webhook'.
        # Free string, validated app-side against a registry — keeps
        # adding a new channel type a code-only change (no migration).
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        # Symbolic trigger names: ['polaris.plan', 'validation.fail',
        # 'run_failed']. Stored as JSONB array; the dispatcher matches
        # against this list on each event ingestion.
        sa.Column("triggers", JSONB(), nullable=False, server_default="[]"),
        # Optional shared secret for HMAC signing on generic webhooks.
        # Slack/Discord/Teams/Mattermost don't use this — those URLs
        # are themselves the auth secret.
        sa.Column("secret_token", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id", "name",
            name="uq_notification_channels_workspace_name",
        ),
    )
    op.create_index(
        "idx_notification_channels_workspace",
        "notification_channels",
        ["workspace_id"],
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "channel_id",
            sa.String(),
            sa.ForeignKey("notification_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Nullable because test-fires don't have a triggering event.
        # ON DELETE SET NULL so an event purge doesn't take audit rows
        # with it (the response_summary is the durable record).
        sa.Column(
            "event_id",
            sa.BigInteger(),
            sa.ForeignKey("events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Which symbolic trigger fired (e.g., 'polaris.plan').
        sa.Column("trigger", sa.String(length=64), nullable=False),
        # 'sent' | 'failed' | 'skipped'. Free string; new statuses
        # land code-only.
        sa.Column("status", sa.String(length=16), nullable=False),
        # Response code, body snippet, error message — whatever the
        # dispatcher captured. Plain dict for forward-compatibility.
        sa.Column("response_summary", JSONB(), nullable=True),
        sa.Column(
            "attempt_count", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Hot path: "show me the last N deliveries for this channel."
    op.create_index(
        "idx_notification_deliveries_channel_sent",
        "notification_deliveries",
        ["channel_id", "sent_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_notification_deliveries_channel_sent",
        table_name="notification_deliveries",
    )
    op.drop_table("notification_deliveries")
    op.drop_index(
        "idx_notification_channels_workspace",
        table_name="notification_channels",
    )
    op.drop_table("notification_channels")
