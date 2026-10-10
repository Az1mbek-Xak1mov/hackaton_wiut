"""borrower STIR optional (owner self sign-up)

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("borrowers", "stir", existing_type=sa.String(length=9), nullable=True)


def downgrade() -> None:
    op.alter_column("borrowers", "stir", existing_type=sa.String(length=9), nullable=False)
