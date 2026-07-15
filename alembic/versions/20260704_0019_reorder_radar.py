"""Reorder Radar — operator qo'ng'iroqlari jurnali + churn sozlamasi.

Revision ID: 0019_reorder_radar
Revises: 0018_finance_cogs_expenses
Create Date: 2026-07-04

O'zgarishlar:
  * operator_calls — operator qo'ng'iroqlari (append-only): natija, snooze, izoh.
  * app_settings.radar_churn_after_days — OVERDUE → CHURNED chegarasi (kun).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_reorder_radar"
down_revision = "0018_finance_cogs_expenses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operator_calls",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("customer_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operator_id", sa.BigInteger(), nullable=False),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("snooze_until", sa.Date(), nullable=True),
        sa.Column("note", sa.String(255), nullable=False, server_default=""),
    )
    op.create_index("ix_operator_calls_customer_id", "operator_calls", ["customer_id"])
    op.create_index(
        "ix_operator_calls_customer_called", "operator_calls", ["customer_id", "called_at"],
    )
    op.add_column("app_settings", sa.Column(
        "radar_churn_after_days", sa.Integer(), nullable=False, server_default="14"))


def downgrade() -> None:
    op.drop_column("app_settings", "radar_churn_after_days")
    op.drop_index("ix_operator_calls_customer_called", table_name="operator_calls")
    op.drop_index("ix_operator_calls_customer_id", table_name="operator_calls")
    op.drop_table("operator_calls")
