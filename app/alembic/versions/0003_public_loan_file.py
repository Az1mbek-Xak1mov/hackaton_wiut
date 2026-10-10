"""public loan-file check on /analyse: applications.is_public/expires_at, borrowers.is_public

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("applications", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_applications_expires_at", "applications", ["expires_at"])
    op.add_column("borrowers", sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("borrowers", "is_public")
    op.drop_index("ix_applications_expires_at", table_name="applications")
    op.drop_column("applications", "expires_at")
    op.drop_column("applications", "is_public")
