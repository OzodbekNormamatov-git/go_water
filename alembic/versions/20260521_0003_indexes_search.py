"""Performance indekslari: trigram search + created_at sortlash.

Revision ID: 0003_indexes
Revises: 0002_loyalty
Create Date: 2026-05-21

Maqsad: katta bazada (10k+ mijoz, 100k+ buyurtma) admin paneli ish tezligi:

  1. `users.full_name` va `users.phone_number` ustida **trigram (pg_trgm) GIN**
     indeks — `ilike '%abc%'` so'rovini sequential scan'siz ishlatadi.

  2. `users.created_at DESC` va `orders.created_at DESC` indekslari — admin
     ro'yxatlarining standart tartibi shu, har sahifa fetch tez bo'lishi uchun.

  3. `customer_addresses (customer_id, is_default)` — default address tezda
     topiladi.

CONCURRENTLY ishlatamiz — production'da jadval bloklanmasin. Lekin Alembic
default transactional DDL bilan ishlaydi; CONCURRENTLY tranzaksiya ichida ishlamaydi,
shuning uchun har bir CREATE INDEX uchun avtokommit context ochamiz.
"""
from __future__ import annotations

from alembic import op

revision = "0003_indexes"
down_revision = "0002_loyalty"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pg_trgm extension — odatda PG14+ default-paketda mavjud (postgresql-contrib).
    # IF NOT EXISTS — qayta yugurganda xato bo'lmasin.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # CONCURRENTLY bloklanmaslik uchun har birini avtokommit bilan ishga tushiramiz.
    # Bu jadval qulflanmasligini va production load'ni minimize qiladi.
    connection = op.get_bind()
    with connection.execution_options(isolation_level="AUTOCOMMIT"):
        # ---- users: trigram search indekslari (full_name + phone_number)
        connection.exec_driver_sql(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_users_full_name_trgm "
            "ON users USING gin (full_name gin_trgm_ops)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_users_phone_trgm "
            "ON users USING gin (phone_number gin_trgm_ops)"
        )

        # ---- users.created_at DESC (admin "yangi mijozlar" ro'yxati uchun)
        connection.exec_driver_sql(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_users_created_at_desc "
            "ON users (created_at DESC)"
        )

        # ---- orders.created_at DESC (eng so'nggi buyurtmalar ro'yxati)
        connection.exec_driver_sql(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_orders_created_at_desc "
            "ON orders (created_at DESC)"
        )

        # ---- orders (status, created_at DESC) — admin dashboardda status bo'yicha filter
        connection.exec_driver_sql(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_orders_status_created_at "
            "ON orders (status, created_at DESC)"
        )

        # ---- orders.delivered_at DESC — kuryer DELIVERED statistikasi tezroq
        connection.exec_driver_sql(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_orders_delivered_at "
            "ON orders (delivered_at DESC) WHERE delivered_at IS NOT NULL"
        )

        # ---- customer_addresses (customer_id, is_default) — partial: faqat default
        connection.exec_driver_sql(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_customer_addresses_default "
            "ON customer_addresses (customer_id) WHERE is_default = true"
        )


def downgrade() -> None:
    connection = op.get_bind()
    with connection.execution_options(isolation_level="AUTOCOMMIT"):
        for name in (
            "ix_customer_addresses_default",
            "ix_orders_delivered_at",
            "ix_orders_status_created_at",
            "ix_orders_created_at_desc",
            "ix_users_created_at_desc",
            "ix_users_phone_trgm",
            "ix_users_full_name_trgm",
        ):
            connection.exec_driver_sql(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
