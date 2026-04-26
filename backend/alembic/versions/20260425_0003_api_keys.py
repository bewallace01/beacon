"""api_keys table; drop workspaces.api_key; seed hashed demo-key

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-25
"""
import hashlib
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
DEMO_KEY = "demo-key"


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("prefix", sa.String(), nullable=False),
        sa.Column("hash", sa.String(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_api_keys_workspace", "api_keys", ["workspace_id"]
    )

    # Seed: an api_key for the default workspace whose plaintext is "demo-key".
    # This preserves the existing demo bot's behavior under the new auth model.
    demo_hash = hashlib.sha256(DEMO_KEY.encode()).hexdigest()
    demo_key_id = str(uuid.uuid4())
    op.execute(
        f"""
        INSERT INTO api_keys (id, workspace_id, name, prefix, hash, created_at)
        VALUES (
            '{demo_key_id}',
            '{DEFAULT_WORKSPACE_ID}',
            'seed',
            'demo-key',
            '{demo_hash}',
            now()
        )
        """
    )

    # The plaintext column is no longer needed: lookup is via the api_keys.hash
    # column. Dropping it removes the temptation to read it.
    op.drop_column("workspaces", "api_key")


def downgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("api_key", sa.String(), nullable=True, unique=True),
    )
    op.execute(
        f"UPDATE workspaces SET api_key = '{DEMO_KEY}' "
        f"WHERE id = '{DEFAULT_WORKSPACE_ID}'"
    )
    op.alter_column("workspaces", "api_key", nullable=False)
    op.drop_index("idx_api_keys_workspace", table_name="api_keys")
    op.drop_table("api_keys")
