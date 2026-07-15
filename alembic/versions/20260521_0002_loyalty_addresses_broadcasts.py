"""Cashback + bottle balance + address book + broadcasts.

Revision ID: 0002_loyalty
Revises: 0001_baseline
Create Date: 2026-05-21

Bu migratsiya quyidagilarni qo'shadi:
  * users.cashback_balance NUMERIC(12,2) NOT NULL DEFAULT 0  + CHECK >= 0
  * users.bottles_balance  INTEGER       NOT NULL DEFAULT 0  + CHECK >= 0
  * orders.items_total, cashback_used, cashback_earned NUMERIC(12,2)
  * orders.bottles_issued, bottles_returned INTEGER
  * orders.address_label, address_details
  * customer_addresses jadvali
  * broadcasts jadvali

Mavjud bazalarda — `Data/database.py` ichidagi idempotent ALTER'lar
xuddi shu sxema o'zgarishlarini qiladi (qo'shimcha xavfsizlik qatlami).
Alembic'ni yangi muhitlarda yagona rasmiy migratsiya manbai sifatida
ishlatish tavsiya etiladi.
"""
from __future__ import annotations

from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision = "0002_loyalty"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- users ----------
    op.add_column(
        "users",
        sa.Column(
            "cashback_balance",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "bottles_balance",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_check_constraint(
        "ck_users_cashback_nonneg", "users", "cashback_balance >= 0",
    )
    op.create_check_constraint(
        "ck_users_bottles_nonneg", "users", "bottles_balance >= 0",
    )

    # ---------- orders ----------
    op.add_column(
        "orders",
        sa.Column("items_total", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "orders",
        sa.Column("cashback_used", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "orders",
        sa.Column("cashback_earned", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "orders",
        sa.Column("bottles_issued", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "orders",
        sa.Column("bottles_returned", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "orders",
        sa.Column("address_label", sa.String(40), nullable=False, server_default=""),
    )
    op.add_column(
        "orders",
        sa.Column("address_details", sa.String(200), nullable=False, server_default=""),
    )
    # Eski yozuvlarda items_total = total_amount
    op.execute(
        "UPDATE orders SET items_total = total_amount WHERE items_total = 0 AND total_amount > 0"
    )

    # ---------- customer_addresses ----------
    op.create_table(
        "customer_addresses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_customer_addresses_customer_id_users"),
            nullable=False,
            index=True,
        ),
        sa.Column("label", sa.String(40), nullable=False),
        sa.Column("details", sa.String(200), nullable=False, server_default=""),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("customer_id", "label", name="uq_customer_addresses_customer_label"),
    )

    # ---------- broadcasts ----------
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(80), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "sending", "done", "failed", "cancelled",
                name="broadcast_status", native_enum=False, length=16,
            ),
            nullable=False,
            server_default="pending",
            index=True,
        ),
        sa.Column("total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sent", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("broadcasts")
    op.drop_table("customer_addresses")
    for col in (
        "address_details", "address_label",
        "bottles_returned", "bottles_issued",
        "cashback_earned", "cashback_used", "items_total",
    ):
        op.drop_column("orders", col)
    op.drop_constraint("ck_users_bottles_nonneg", "users", type_="check")
    op.drop_constraint("ck_users_cashback_nonneg", "users", type_="check")
    op.drop_column("users", "bottles_balance")
    op.drop_column("users", "cashback_balance")
