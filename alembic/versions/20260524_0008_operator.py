"""Operator (call operator) — order yaratish + has_started_bot bayrog'i.

Revision ID: 0008_operator
Revises: 0007_arrived
Create Date: 2026-05-24

Qo'shilgan ustunlar:
  * orders.created_by_operator_id (BIGINT NULL)
        — operator yaratgan buyurtmalarda operator'ning Telegram ID si
        — NULL = mijoz o'zi botdan yaratgan
  * users.has_started_bot (BOOLEAN DEFAULT false)
        — mijoz bot bilan o'zaro aloqada bo'lganmi
        — False bo'lsa DM xabarlar yuborilmaydi (silent skip)

Backfill: mavjud mijozlar (real, ijobiy telegram_id) `has_started_bot=true`
deb belgilanadi — ular bot orqali ro'yxatdan o'tgan. Yangi sintetik
manfiy telegram_id'li (operator yaratgan) mijozlar `false` qoladi.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_operator"
down_revision = "0007_arrived"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("created_by_operator_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_orders_created_by_operator_id",
        "orders",
        ["created_by_operator_id"],
        postgresql_where=sa.text("created_by_operator_id IS NOT NULL"),
    )
    op.add_column(
        "users",
        sa.Column(
            "has_started_bot", sa.Boolean(),
            nullable=False, server_default=sa.text("false"),
        ),
    )
    op.execute(
        "UPDATE users SET has_started_bot = true "
        "WHERE has_started_bot = false AND telegram_id > 0"
    )


def downgrade() -> None:
    op.drop_column("users", "has_started_bot")
    op.drop_index("ix_orders_created_by_operator_id", table_name="orders")
    op.drop_column("orders", "created_by_operator_id")
