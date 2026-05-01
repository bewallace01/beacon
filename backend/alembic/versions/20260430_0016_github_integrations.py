"""github_integrations: workspace ↔ GitHub repo + per-agent path mapping

Phase 10.1 of the GitHub-integration rollout. Two tables:

  github_integrations   one row per workspace (UNIQUE workspace_id),
                        carries the repo + branch + encrypted PAT +
                        encrypted webhook secret. The webhook secret
                        is what GitHub HMAC-signs incoming webhook
                        payloads against; we generate it on first
                        registration and reveal it once so the user
                        can paste it into GitHub's webhook config.
                        After that it stays encrypted at rest.

  github_agent_paths    workspace + agent → path-within-the-repo.
                        Composite PK on (workspace_id, agent_name).
                        A push that touches files under a registered
                        path triggers a redeploy of that agent in
                        Phase 10.3.

Both tables use existing secrets_crypto.encrypt() / decrypt() for the
encrypted columns — same pattern as WorkspaceSecret rows. The
LIGHTSEI_SECRETS_KEY env var is the workspace-key used for both.

One repo per workspace in v1 (enforced via UNIQUE(workspace_id) on
github_integrations). Multi-repo + per-environment branch tracking
lands in Phase 10B if there's demand.

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "github_integrations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # GitHub repo identity. Together with `branch` these form the
        # natural key the webhook receiver uses to route inbound
        # pushes to the right workspace.
        sa.Column("repo_owner", sa.String(length=255), nullable=False),
        sa.Column("repo_name", sa.String(length=255), nullable=False),
        sa.Column(
            "branch", sa.String(length=255), nullable=False, server_default="main"
        ),
        # Both encrypted via secrets_crypto.encrypt() — same scheme as
        # WorkspaceSecret rows. Plaintext is never stored.
        sa.Column("encrypted_pat", sa.Text(), nullable=False),
        sa.Column("encrypted_webhook_secret", sa.Text(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id", name="uq_github_integrations_workspace"
        ),
    )

    op.create_table(
        "github_agent_paths",
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "agent_name", sa.String(length=64), primary_key=True, nullable=False
        ),
        # Repo-relative path. No leading slash, no `..` segments —
        # validated app-side at the endpoint layer (see 10.4 in
        # main.py). Forward slashes for nested dirs ("bots/x/y").
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("github_agent_paths")
    op.drop_table("github_integrations")
