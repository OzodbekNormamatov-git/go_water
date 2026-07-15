"""Per-mahsulot minimal buyurtma soni — Food.min_quantity (global o'rniga).

Revision ID: 0013_food_min_qty
Revises: 0012_courier_cash
Create Date: 2026-06-11

O'zgarishlar:
  * `foods.min_quantity INTEGER NOT NULL DEFAULT 1` — har mahsulot uchun
    minimal buyurtma soni (1 = cheklov yo'q). Admin Mini App'da belgilanadi,
    buyurtma yaratishda server har item uchun tekshiradi.
  * `app_settings.min_order_quantity` DROP — global minimal buyurtma bekor
    qilindi (per-mahsulot min bilan almashtirildi). Admin qiymati yo'qoladi —
    bu qasddan (yangi tizimga o'tish).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_food_min_qty"
down_revision = "0012_courier_cash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "foods",
        sa.Column(
            "min_quantity",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.drop_column("app_settings", "min_order_quantity")


def downgrade() -> None:
    # Global sozlama qaytariladi (admin qiymati yo'qolgan — default 1).
    op.add_column(
        "app_settings",
        sa.Column(
            "min_order_quantity",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.drop_column("foods", "min_quantity")
