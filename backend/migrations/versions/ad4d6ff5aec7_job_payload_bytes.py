"""job payload bytes

Revision ID: ad4d6ff5aec7
Revises: 5b3c1808a17f
Create Date: 2026-11-10 01:32:03.526622

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ad4d6ff5aec7"
down_revision: str | Sequence[str] | None = "5b3c1808a17f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("jobs", sa.Column("payload", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("jobs", "payload")
