"""Avto-eslatma (predictive reorder) — sozlama ustunlari + reminders jadvali.

Revision ID: 0016_auto_reminders
Revises: 0015_ledger_entries
Create Date: 2026-06-24

O'zgarishlar:
  * app_settings.reminders_enabled (BOOL, default true) — dasturni yoqish/o'chirish
  * app_settings.reminder_lead_days (INT, default 1) — sikl tugashidan necha kun oldin
  * users.reminders_enabled (BOOL, default true) — per-mijoz opt-out
  * reminders jadvali — yuborilgan eslatmalar jurnali (dedup, churn-cap, audit)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_auto_reminders"
down_revision = "0015_ledger_entries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column(
        "reminders_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("app_settings", sa.Column(
        "reminder_lead_days", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("users", sa.Column(
        "reminders_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")))

    op.create_table(
        "reminders",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("customer_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("cycle_days", sa.Numeric(8, 2), nullable=False),
        sa.Column("anchor_order_id", sa.Integer(),
                  sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reordered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_reminders_customer", "reminders", ["customer_id", "sent_at"])


def downgrade() -> None:
    op.drop_index("ix_reminders_customer", table_name="reminders")
    op.drop_table("reminders")
    op.drop_column("users", "reminders_enabled")
    op.drop_column("app_settings", "reminder_lead_days")
    op.drop_column("app_settings", "reminders_enabled")
