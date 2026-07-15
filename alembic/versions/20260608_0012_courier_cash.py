"""Kuryer naqd pul balansi — Courier.cash_balance.

Revision ID: 0012_courier_cash
Revises: 0011_min_order_qty
Create Date: 2026-06-08

Qo'shilgan: `couriers.cash_balance NUMERIC(12,2) NOT NULL DEFAULT 0` + CHECK >= 0.

Buyurtma DELIVERED bo'lganda mijozdan olingan naqd (`total_amount`) shu balansga
qo'shiladi. Admin har kuryerda qancha naqd borligini ko'radi; kuryer pulni
topshirganda admin "qabul qildim" (settle) bilan kamaytiradi.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_courier_cash"
down_revision = "0011_min_order_qty"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "couriers",
        sa.Column(
            "cash_balance",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_couriers_cash_nonneg",
        "couriers",
        "cash_balance >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_couriers_cash_nonneg", "couriers", type_="check")
    op.drop_column("couriers", "cash_balance")
