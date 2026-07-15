"""Moliya: mahsulot tannarxi (COGS) + kompaniya rasxodlari (P&L poydevori).

Revision ID: 0018_finance_cogs_expenses
Revises: 0017_user_phones
Create Date: 2026-07-04

O'zgarishlar:
  * foods.cost_price — tannarx (admin kiritadi)
  * order_items.unit_cost — buyurtma paytidagi tannarx SNAPSHOT'i
  * expense_categories — kengayuvchan kategoriyalar (jadval, enum emas)
  * recurring_expenses — doimiy rasxod shabloni (har davr materializatsiya)
  * expenses — konkret rasxod yozuvlari (hisobot shulardan o'qiydi)
    UNIQUE(recurring_id, spent_on) — idempotent materializatsiya kaliti.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_finance_cogs_expenses"
down_revision = "0017_user_phones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("foods", sa.Column(
        "cost_price", sa.Numeric(12, 2), nullable=False, server_default="0"))
    op.add_column("order_items", sa.Column(
        "unit_cost", sa.Numeric(12, 2), nullable=False, server_default="0"))

    op.create_table(
        "expense_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_expense_categories_name", "expense_categories", ["name"])

    op.create_table(
        "recurring_expenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.Integer(),
                  sa.ForeignKey("expense_categories.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("label", sa.String(120), nullable=False, server_default=""),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("period", sa.String(16), nullable=False, server_default="monthly"),
        sa.Column("anchor_day", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("anchor_month", sa.SmallInteger(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_recurring_expenses_category_id", "recurring_expenses", ["category_id"])

    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.Integer(),
                  sa.ForeignKey("expense_categories.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("spent_on", sa.Date(), nullable=False),
        sa.Column("note", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("recurring_id", sa.Integer(),
                  sa.ForeignKey("recurring_expenses.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_expenses_category_id", "expenses", ["category_id"])
    op.create_index("ix_expenses_spent_on_desc", "expenses", ["spent_on"])
    op.create_index(
        "uq_expenses_recurring_period", "expenses", ["recurring_id", "spent_on"],
        unique=True, postgresql_where=sa.text("recurring_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_expenses_recurring_period", table_name="expenses")
    op.drop_index("ix_expenses_spent_on_desc", table_name="expenses")
    op.drop_index("ix_expenses_category_id", table_name="expenses")
    op.drop_table("expenses")
    op.drop_index("ix_recurring_expenses_category_id", table_name="recurring_expenses")
    op.drop_table("recurring_expenses")
    op.drop_index("ix_expense_categories_name", table_name="expense_categories")
    op.drop_table("expense_categories")
    op.drop_column("order_items", "unit_cost")
    op.drop_column("foods", "cost_price")
