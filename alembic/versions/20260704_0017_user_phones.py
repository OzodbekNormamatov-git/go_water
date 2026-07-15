"""Ko'p telefon raqam — user_phones jadvali + mavjud raqamlarni backfill.

Revision ID: 0017_user_phones
Revises: 0016_auto_reminders
Create Date: 2026-07-04

O'zgarishlar:
  * user_phones jadvali — bir mijozga cheklanmagan sonda raqam (one-to-many).
    `phone` GLOBAL unique — identifikatsiya kaliti (bitta raqam = bitta mijoz).
  * Partial unique (user_id WHERE is_primary) — har mijozda bitta primary.
  * Backfill: users.phone_number → user_phones (is_primary=true).
    `users.phone_number` KESH sifatida qoladi (primary raqam nusxasi).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_user_phones"
down_revision = "0016_auto_reminders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_phones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("label", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
    )
    op.create_index("ix_user_phones_user_id", "user_phones", ["user_id"])
    op.create_index("ix_user_phones_phone", "user_phones", ["phone"], unique=True)
    op.create_index(
        "uq_user_phones_primary_per_user", "user_phones", ["user_id"],
        unique=True, postgresql_where=sa.text("is_primary"),
    )
    # Backfill — har mavjud mijozning primary raqami.
    op.execute(
        """INSERT INTO user_phones (user_id, phone, is_primary, created_at, updated_at)
           SELECT id, phone_number, true, NOW(), NOW() FROM users
           WHERE phone_number IS NOT NULL AND phone_number <> ''"""
    )


def downgrade() -> None:
    op.drop_index("uq_user_phones_primary_per_user", table_name="user_phones")
    op.drop_index("ix_user_phones_phone", table_name="user_phones")
    op.drop_index("ix_user_phones_user_id", table_name="user_phones")
    op.drop_table("user_phones")
