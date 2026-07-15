"""Kunlik buyurtma raqami — daily_number + atomik counter jadval.

Revision ID: 0010_daily_number
Revises: 0009_courier_phone
Create Date: 2026-06-07

Qo'shilgan:
  * orders.daily_number INTEGER NULL — har kuni 1 dan boshlanadigan ko'rinadigan raqam
    (NULL = eski buyurtmalar, display'da #id ga fallback)
  * daily_order_counters (day DATE PK, last_number INTEGER) — atomik kunlik counter

ESLATMA: eski buyurtmalarni backfill QILMAYMIZ (daily_number NULL qoladi).
Keyinroq alohida data-migration bilan tarixiy raqamlar beriladi. Yangi
buyurtmalar deploy'dan keyin darhol daily_number oladi.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_daily_number"
down_revision = "0009_courier_phone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("daily_number", sa.Integer(), nullable=True),
    )
    op.create_table(
        "daily_order_counters",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("last_number", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("daily_order_counters")
    op.drop_column("orders", "daily_number")
