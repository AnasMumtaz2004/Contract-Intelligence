"""add the supported claims to citations

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the claims column."""
    op.add_column("citations", sa.Column("claims_json", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove the claims column."""
    op.drop_column("citations", "claims_json")