"""Soft delete — `deleted_at` ustun 4 ta jadvalda.

Revision ID: 0006_soft_delete
Revises: 0005_bcast_photo
Create Date: 2026-05-24

Qo'shilgan jadvallar (deleted_at TIMESTAMPTZ NULL):
  foods, users, couriers, orders

Partial indekslar (faqat aktiv qatorlar uchun) — eng tez-tez ishlatiladigan
filter (`WHERE deleted_at IS NULL`) millisekundlarda javob bersin.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_soft_delete"
down_revision = "0005_bcast_photo"
branch_labels = None
depends_on = None


_TABLES = ("foods", "users", "couriers", "orders")


def upgrade() -> None:
    for tbl in _TABLES:
        op.add_column(tbl, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index(f"ix_{tbl}_deleted_at", tbl, ["deleted_at"])
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{tbl}_active "
            f"ON {tbl} (id) WHERE deleted_at IS NULL"
        )


def downgrade() -> None:
    for tbl in _TABLES:
        op.execute(f"DROP INDEX IF EXISTS ix_{tbl}_active")
        op.drop_index(f"ix_{tbl}_deleted_at", table_name=tbl)
        op.drop_column(tbl, "deleted_at")
