"""workspace ip hash

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-14 12:53:32.334398

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing workspaces get no hash: they do not count towards the limit.
    op.add_column(
        "workspace", sa.Column("ip_hash", sa.String(length=64), nullable=True)
    )
    op.create_index(
        "ix_workspace_ip_hash_created_at",
        "workspace",
        ["ip_hash", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_workspace_ip_hash_created_at", table_name="workspace")
    op.drop_column("workspace", "ip_hash")
