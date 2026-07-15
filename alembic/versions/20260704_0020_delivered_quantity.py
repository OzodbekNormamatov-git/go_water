"""Kuryer yetkazgan haqiqiy dona — order_items.delivered_quantity.

Revision ID: 0020_delivered_quantity
Revises: 0019_reorder_radar
Create Date: 2026-07-04

Sabab: mijoz "4 ta" deb buyurtma qilib eshik oldida 6 ta olishi mumkin. Kuryer
yetkazgan haqiqiy dona shu ustunga yoziladi; NULL = o'zgartirmagan (= buyurtilgan).
Buyurtma moliyasi (narx, keshbek, idish, kuryer naqdi) COALESCE(delivered, quantity)
dan noldan qayta hisoblanadi. `quantity` — mijoz buyurtma qilgan asl (snapshot).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_delivered_quantity"
down_revision = "0019_reorder_radar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "order_items",
        sa.Column("delivered_quantity", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_items", "delivered_quantity")
