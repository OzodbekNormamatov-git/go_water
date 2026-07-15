"""ARRIVED status — kuryer yetib keldi, tasdiq kutilmoqda.

Revision ID: 0007_arrived
Revises: 0006_soft_delete
Create Date: 2026-05-24

Qo'shilgan ustunlar:
  * orders.customer_arrived_message_id BIGINT NULL
        — kuryer ARRIVED bo'lganda mijozga yuborilgan "yetib keldi" bildirishnoma id'si
        — DELIVERED bo'lganda o'sha xabar o'chiriladi
  * orders.arrived_at TIMESTAMPTZ NULL — ARRIVED holatga o'tgan vaqt

Yangi OrderStatus qiymati ARRIVED — enum string ustun (native_enum=False),
shu sababli alohida CHECK constraint yangilash kerak emas, application
qatlamida validatsiya bo'ladi.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_arrived"
down_revision = "0006_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("customer_arrived_message_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "arrived_at")
    op.drop_column("orders", "customer_arrived_message_id")
