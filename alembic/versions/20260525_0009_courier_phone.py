"""Kuryer telefon raqami — mijozga qo'ng'iroq qilish uchun.

Revision ID: 0009_courier_phone
Revises: 0008_operator
Create Date: 2026-05-25

Yangi ustun: `couriers.phone_number VARCHAR(20) NULL`.

NULL bo'lishi mumkin: eski kuryerlar va botga /start contact share qilmagan
kuryerlar uchun. Format E.164 (+998901234567) Service qatlamida normalize
qilinadi. Mijoz `tel:` link bilan qo'ng'iroq qila oladi.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_courier_phone"
down_revision = "0008_operator"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "couriers",
        sa.Column("phone_number", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("couriers", "phone_number")
