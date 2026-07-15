"""Append-only moliyaviy jurnal — ledger_entries + mavjud balanslarni backfill.

Revision ID: 0015_ledger_entries
Revises: 0014_bottles_per_unit
Create Date: 2026-06-24

O'zgarishlar:
  * `ledger_entries` jadvali — cashback/bottles/cash balanslarining o'zgarmas
    tarixi (subject_type/id, account, kind, delta, balance_after, order_id,
    operator_id, reason, idempotency_key, created_at).
  * Indekslar: subyekt tarixi, order bo'yicha, idempotency (partial unique).
  * BACKFILL: har mavjud nolga teng bo'lmagan balans uchun bitta
    `opening_balance` seed yozuvi — shunda har bir balans summasi jurnaldan
    to'liq tiklanadi (haqiqiy audit). Idempotent (NOT EXISTS bilan himoyalangan).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_ledger_entries"
down_revision = "0014_bottles_per_unit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("account", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("delta", sa.Numeric(14, 2), nullable=False),
        sa.Column("balance_after", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "order_id", sa.Integer(),
            sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("operator_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index(
        "ix_ledger_subject", "ledger_entries",
        ["subject_type", "subject_id", "account", "id"],
    )
    op.create_index("ix_ledger_order_id", "ledger_entries", ["order_id"])
    op.create_index(
        "uq_ledger_idempotency", "ledger_entries",
        ["subject_type", "subject_id", "account", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # ---- Backfill: mavjud balanslarni opening_balance seed yozuvi bilan ----
    _OPENING = "Ochilish balansi (ledger joriy etildi)"
    op.execute(f"""
        INSERT INTO ledger_entries
            (subject_type, subject_id, account, kind, delta, balance_after, reason, created_at)
        SELECT 'user', id, 'cashback', 'opening_balance',
               cashback_balance, cashback_balance, '{_OPENING}', NOW()
        FROM users
        WHERE cashback_balance <> 0
          AND NOT EXISTS (
            SELECT 1 FROM ledger_entries le
            WHERE le.subject_type='user' AND le.subject_id=users.id AND le.account='cashback'
          )
    """)
    op.execute(f"""
        INSERT INTO ledger_entries
            (subject_type, subject_id, account, kind, delta, balance_after, reason, created_at)
        SELECT 'user', id, 'bottles', 'opening_balance',
               bottles_balance, bottles_balance, '{_OPENING}', NOW()
        FROM users
        WHERE bottles_balance <> 0
          AND NOT EXISTS (
            SELECT 1 FROM ledger_entries le
            WHERE le.subject_type='user' AND le.subject_id=users.id AND le.account='bottles'
          )
    """)
    op.execute(f"""
        INSERT INTO ledger_entries
            (subject_type, subject_id, account, kind, delta, balance_after, reason, created_at)
        SELECT 'courier', id, 'cash', 'opening_balance',
               cash_balance, cash_balance, '{_OPENING}', NOW()
        FROM couriers
        WHERE cash_balance <> 0
          AND NOT EXISTS (
            SELECT 1 FROM ledger_entries le
            WHERE le.subject_type='courier' AND le.subject_id=couriers.id AND le.account='cash'
          )
    """)


def downgrade() -> None:
    op.drop_index("uq_ledger_idempotency", table_name="ledger_entries")
    op.drop_index("ix_ledger_order_id", table_name="ledger_entries")
    op.drop_index("ix_ledger_subject", table_name="ledger_entries")
    op.drop_table("ledger_entries")
