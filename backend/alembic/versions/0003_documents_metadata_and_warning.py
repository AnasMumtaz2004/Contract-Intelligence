"""add document metadata columns and the message warning

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the new columns to documents and messages."""
    op.add_column("documents", sa.Column("effective_date", sa.Date(), nullable=True))
    op.add_column("documents", sa.Column("parent_document_id", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("parser_used", sa.String(length=50), server_default="pymupdf", nullable=False))
    op.add_column("documents", sa.Column("parse_quality", sa.Float(), nullable=True))
    op.create_foreign_key(
        "fk_documents_parent_document_id",
        "documents",
        "documents",
        ["parent_document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_documents_parent_document_id", "documents", ["parent_document_id"])

    op.add_column("messages", sa.Column("warning", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove the new columns."""
    op.drop_column("messages", "warning")
    op.drop_index("ix_documents_parent_document_id", table_name="documents")
    op.drop_constraint("fk_documents_parent_document_id", "documents", type_="foreignkey")
    op.drop_column("documents", "parse_quality")
    op.drop_column("documents", "parser_used")
    op.drop_column("documents", "parent_document_id")
    op.drop_column("documents", "effective_date")