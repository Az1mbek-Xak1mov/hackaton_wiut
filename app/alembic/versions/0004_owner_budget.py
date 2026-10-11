"""owner budget: budget_lines (monthly plan) and budget_advice (last advice run)

Revision ID: 0004_owner_budget
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_owner_budget"
down_revision = "0003"
branch_labels = None
depends_on = None


def _base() -> list:
    return [sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("uuid", sa.Uuid(), nullable=False, unique=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now())]


def upgrade() -> None:
    op.create_table(
        "budget_lines", *_base(),
        sa.Column("borrower_id", sa.Integer(), sa.ForeignKey("borrowers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("category", sa.String(32), nullable=False, server_default="total"),
        sa.Column("planned_income", sa.Numeric(20, 2), nullable=True),
        sa.Column("planned_spending", sa.Numeric(20, 2), nullable=True),
        sa.UniqueConstraint("borrower_id", "month", "category", name="uq_budget_line"),
    )
    op.create_index("ix_budget_lines_borrower_id", "budget_lines", ["borrower_id"])
    op.create_table(
        "budget_advice", *_base(),
        sa.Column("borrower_id", sa.Integer(), sa.ForeignKey("borrowers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False, server_default="rules"),
        sa.Column("items", sa.JSON(), nullable=False),
    )
    op.create_index("ix_budget_advice_borrower_id", "budget_advice", ["borrower_id"])


def downgrade() -> None:
    op.drop_index("ix_budget_advice_borrower_id", table_name="budget_advice")
    op.drop_table("budget_advice")
    op.drop_index("ix_budget_lines_borrower_id", table_name="budget_lines")
    op.drop_table("budget_lines")
