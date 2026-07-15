"""Depozit balans + to'lov usuli + operators jadvali + rasxod qamrov davri + telefon backfill.

Revision ID: 0022_deposit_payment_operators
Revises: 0021_rename_radar_to_reorder
Create Date: 2026-07-04

To'rt yangi imkoniyat bitta revisionda (bir releasega tegishli):
  1. `users.deposit_balance` — MChJ mijozlarning oldindan to'lov (avans) balansi.
     CHECK >= 0 (ck_users_deposit_nonneg) — couriers.cash_balance naqshi.
  2. `orders.payment_method` — cash|card|deposit (VARCHAR, SAEnum EMAS —
     enum-nom/qiymat mismatch sinfidan qochamiz). Default 'cash' = eski xulq.
  3. `operators` jadvali — admin bot operatorlari endi DB'da (kuryer patterni,
     .env OPERATOR_TELEGRAM_IDS o'rniga; seed main.py'da).
  4. `expenses.period_start/period_end` — oldindan to'langan rasxodning qamrov
     davri; hisobot summani davr kunlariga proportsional taqsimlaydi.

Qo'shimcha tozalash:
  * Telefon backfill: '+' + 9 raqam (998'siz saqlangan) → '+998...' formatga.
    UNIQUE to'qnashuvlar (ikkala forma alohida mijoz sifatida mavjud bo'lsa)
    tegilmaydi — qo'lda merge talab qilinadi.
  * recurring_expenses.period server_default 'monthly' → 'MONTHLY' (ORM enum
    NOMlarni saqlaydi; kichik harfli qiymat barcha o'qishlarni sindirardi).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_deposit_payment_operators"
down_revision = "0021_rename_radar_to_reorder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- 1. users.deposit_balance ----
    op.add_column(
        "users",
        sa.Column(
            "deposit_balance", sa.Numeric(12, 2),
            nullable=False, server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_users_deposit_nonneg", "users", "deposit_balance >= 0",
    )

    # ---- 2. orders.payment_method ----
    op.add_column(
        "orders",
        sa.Column(
            "payment_method", sa.String(16),
            nullable=False, server_default="cash",
        ),
    )

    # ---- 3. operators jadvali ----
    op.create_table(
        "operators",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("telegram_id", sa.BigInteger, nullable=False),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("phone_number", sa.String(20), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("has_started_bot", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_operators_telegram_id", "operators", ["telegram_id"], unique=True)
    op.create_index("ix_operators_deleted_at", "operators", ["deleted_at"])

    # ---- 4. expenses qamrov davri ----
    op.add_column("expenses", sa.Column("period_start", sa.Date, nullable=True))
    op.add_column("expenses", sa.Column("period_end", sa.Date, nullable=True))
    # Ikkalasi birga NULL yoki birga to'ldirilgan; end >= start.
    op.create_check_constraint(
        "ck_expenses_period_valid",
        "expenses",
        "(period_start IS NULL AND period_end IS NULL) OR "
        "(period_start IS NOT NULL AND period_end IS NOT NULL AND period_end >= period_start)",
    )

    # ---- 5. Telefon backfill: '+9xxxxxxxx' (9 raqam, 998'siz) → '+998...' ----
    # UNIQUE ustunlarda to'qnashuv bo'lsa (ikkala forma allaqachon alohida
    # yozuv) — qator tegilmaydi (NOT EXISTS guard), qo'lda merge kerak.
    op.execute(
        r"""UPDATE users u SET phone_number = '+998' || substr(phone_number, 2)
            WHERE phone_number ~ '^\+\d{9}$'
              AND NOT EXISTS (
                SELECT 1 FROM users u2
                WHERE u2.phone_number = '+998' || substr(u.phone_number, 2))"""
    )
    op.execute(
        r"""UPDATE user_phones p SET phone = '+998' || substr(phone, 2)
            WHERE phone ~ '^\+\d{9}$'
              AND NOT EXISTS (
                SELECT 1 FROM user_phones p2
                WHERE p2.phone = '+998' || substr(p.phone, 2))"""
    )
    # couriers.phone_number va orders.contact_phone UNIQUE emas — to'g'ridan-to'g'ri.
    op.execute(
        r"""UPDATE couriers SET phone_number = '+998' || substr(phone_number, 2)
            WHERE phone_number ~ '^\+\d{9}$'"""
    )
    op.execute(
        r"""UPDATE orders SET contact_phone = '+998' || substr(contact_phone, 2)
            WHERE contact_phone ~ '^\+\d{9}$'"""
    )

    # ---- 6. recurring_expenses.period enum-nom tozalashi ----
    # ORM enum NOMlarni saqlaydi ('MONTHLY'); server_default qiymat ('monthly')
    # bilan yozilgan qator bo'lsa — o'qishda LookupError. Normallashtiramiz.
    op.execute(
        "UPDATE recurring_expenses SET period = UPPER(period) "
        "WHERE period IN ('monthly', 'weekly', 'yearly')"
    )
    op.alter_column(
        "recurring_expenses", "period", server_default="MONTHLY",
    )


def downgrade() -> None:
    op.alter_column("recurring_expenses", "period", server_default="monthly")
    op.drop_constraint("ck_expenses_period_valid", "expenses", type_="check")
    op.drop_column("expenses", "period_end")
    op.drop_column("expenses", "period_start")
    op.drop_index("ix_operators_deleted_at", table_name="operators")
    op.drop_index("ix_operators_telegram_id", table_name="operators")
    op.drop_table("operators")
    op.drop_column("orders", "payment_method")
    op.drop_constraint("ck_users_deposit_nonneg", "users", type_="check")
    op.drop_column("users", "deposit_balance")
