"""Sanaladigan/sanalmaydigan tovarlar — Food.bottles_per_unit + snapshot.

Revision ID: 0014_bottles_per_unit
Revises: 0013_food_min_qty
Create Date: 2026-06-24

O'zgarishlar:
  * `foods.bottles_per_unit SMALLINT NOT NULL DEFAULT 1` — har dona mahsulot
    necha qaytariladigan idish berishini bildiradi (0 = sanalmaydi: pumpa,
    kuller, filtr; 1 = oddiy idish; N = multi-pack).
  * `order_items.bottles_per_unit SMALLINT NOT NULL DEFAULT 1` — buyurtma
    vaqtidagi qiymat SNAPSHOT'i (mahsulot keyin o'zgarsa eski buyurtma
    hisobi buzilmaydi, xuddi unit_price kabi).

DEFAULT 1 — barcha mavjud mahsulotlar va order_item'lar avvalgidek sanaladi
(eski "har item = 1 idish" xulq-atvori saqlanadi). Admin keyin pumpa/kullerni
0 qilib belgilaydi.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_bottles_per_unit"
down_revision = "0013_food_min_qty"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "foods",
        sa.Column(
            "bottles_per_unit",
            sa.SmallInteger(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "order_items",
        sa.Column(
            "bottles_per_unit",
            sa.SmallInteger(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("order_items", "bottles_per_unit")
    op.drop_column("foods", "bottles_per_unit")
