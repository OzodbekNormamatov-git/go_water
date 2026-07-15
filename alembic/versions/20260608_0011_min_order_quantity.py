"""Minimal buyurtma soni — AppSettings.min_order_quantity.

Revision ID: 0011_min_order_qty
Revises: 0010_daily_number
Create Date: 2026-06-08

Qo'shilgan: `app_settings.min_order_quantity INTEGER NOT NULL DEFAULT 1`.
Default 1 = cheklov yo'q (xulq-atvor o'zgarmaydi). Admin kichik buyurtmalarni
bloklash uchun katta qiymat belgilashi mumkin.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_min_order_qty"
down_revision = "0010_daily_number"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "min_order_quantity",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "min_order_quantity")
