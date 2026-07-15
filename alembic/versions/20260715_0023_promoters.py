"""Promouterlar (uyma-uy ishchilar) — promokod atributsiyasi va KPI bonusi.

Revision ID: 0023_promoters
Revises: 0022_deposit_payment_operators
Create Date: 2026-07-15

Uyma-uy yuruvchi ishchilar mijozlarga borib, botni tushuntiradi va manzil
saqlashga o'rgatadi; so'ng mijozning telefonida o'z promokodini kiritadi.
Keyingi zakazlar o'sha ishchiga yozilib, KPI/bonus hisoblanadi.

  1. `promoters` — ishchi + NOYOB, O'ZGARMAS promokod. Soft delete (Courier
     patterni): ishdan ketgan ishchi ARXIVLANADI, qatori DB'da qoladi —
     shu sababli `orders.promoter_id` FK'si hech qachon buzilmaydi.
  2. `promoter_redemptions` — mijoz ↔ ishchi bog'lanishi. ALOHIDA jadval
     (users'ga ustun EMAS): bu mijozning atributi emas, audit voqeasi.
     `customer_id` UNIQUE — bir mijoz umrida bir marta (race'ning yakuniy
     himoyasi: parallel ikkinchi so'rov IntegrityError oladi).
     `bonus_window_ends_at` — davr MUHRLANADI (sozlama keyin o'zgarsa,
     mavjud bog'lanishlarning sharti retroaktiv o'zgarmaydi).
  3. `orders` — atributsiya snapshot'i. ATRIBUTSIYA va BONUS ajratilgan:
     `promoter_id`/`promoter_code` bog'lanish bor bo'lsa DOIM yoziladi
     (ishchi ketgan/davr tugagan bo'lsa ham — tahlil buzilmasin), lekin
     `promoter_bonus_amount` faqat shartlar bajarilsa > 0. `cashback_earned`
     patterni: summa yaratilishda muhrlanadi → o'tmish hisobotlari o'zgarmaydi.
  4. `app_settings` — admin boshqaradigan jonli sozlamalar (dastur yoqish,
     bonus summasi, davr uzunligi).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_promoters"
down_revision = "0022_deposit_payment_operators"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- 1. promoters ----
    op.create_table(
        "promoters",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("phone_number", sa.String(20), nullable=True),
        sa.Column("promo_code", sa.String(16), nullable=False),
        # Admin yaratgani uchun default AKTIV (Courier/Operator'dan farqli —
        # ular o'zi /start bosib keladi va admin tasdiqlaydi).
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # UNIQUE: kod noyob. Arxivlangan ishchining kodi ham band bo'lib qoladi —
    # eski zakazlarning `promoter_code` snapshot'i yangi ishchiga tegishli
    # bo'lib ko'rinmasligi kerak (tarix chalkashmasin).
    op.create_index("ix_promoters_promo_code", "promoters", ["promo_code"], unique=True)
    op.create_index("ix_promoters_deleted_at", "promoters", ["deleted_at"])

    # ---- 2. promoter_redemptions ----
    op.create_table(
        "promoter_redemptions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "customer_id", sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        # RESTRICT: bog'lanishi bor promouterni hard-delete qilib bo'lmaydi.
        # Amalda promouterlar arxivlanadi — bu qo'shimcha himoya qavati.
        sa.Column(
            "promoter_id", sa.Integer,
            sa.ForeignKey("promoters.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("promo_code", sa.String(16), nullable=False),
        sa.Column("bonus_window_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # UNIQUE — "bir mijoz, bir marta" qoidasining DB-level kafolati.
    op.create_index(
        "ix_promoter_redemptions_customer_id", "promoter_redemptions",
        ["customer_id"], unique=True,
    )
    op.create_index(
        "ix_promoter_redemptions_promoter_id", "promoter_redemptions", ["promoter_id"],
    )

    # ---- 3. orders atributsiya snapshot'i ----
    op.add_column("orders", sa.Column("promoter_id", sa.Integer, nullable=True))
    # SET NULL: promouter majburan hard-delete qilinsa ham zakaz o'chmaydi.
    op.create_foreign_key(
        "fk_orders_promoter_id_promoters", "orders", "promoters",
        ["promoter_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_orders_promoter_id", "orders", ["promoter_id"])
    # Kod snapshot'i — `order_items.food_name` patterni: promouter qatori
    # yo'qolsa va promoter_id NULL bo'lsa ham audit izi qoladi.
    op.add_column(
        "orders",
        sa.Column("promoter_code", sa.String(16), nullable=False, server_default=""),
    )
    op.add_column(
        "orders",
        sa.Column(
            "promoter_bonus_amount", sa.Numeric(12, 2),
            nullable=False, server_default="0",
        ),
    )
    # Bonus manfiy bo'la olmaydi (users.cashback_balance / couriers.cash_balance
    # naqshi — pul ustunlariga DB-level himoya).
    op.create_check_constraint(
        "ck_orders_promoter_bonus_nonneg", "orders", "promoter_bonus_amount >= 0",
    )

    # ---- 4. app_settings — jonli sozlamalar ----
    op.add_column(
        "app_settings",
        sa.Column(
            "promoter_program_enabled", sa.Boolean,
            nullable=False, server_default=sa.true(),
        ),
    )
    # Default 0: dastur yoqiq bo'lsa-da, admin summani ataylab belgilamaguncha
    # hech kimga pul yozilmaydi (tasodifiy xarajatdan himoya).
    op.add_column(
        "app_settings",
        sa.Column(
            "promoter_bonus_per_order", sa.Numeric(12, 2),
            nullable=False, server_default="0",
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "promoter_bonus_window_days", sa.Integer,
            nullable=False, server_default="90",
        ),
    )
    op.create_check_constraint(
        "ck_app_settings_promoter_bonus_nonneg", "app_settings",
        "promoter_bonus_per_order >= 0",
    )
    op.create_check_constraint(
        "ck_app_settings_promoter_window_positive", "app_settings",
        "promoter_bonus_window_days >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_app_settings_promoter_window_positive", "app_settings", type_="check",
    )
    op.drop_constraint(
        "ck_app_settings_promoter_bonus_nonneg", "app_settings", type_="check",
    )
    op.drop_column("app_settings", "promoter_bonus_window_days")
    op.drop_column("app_settings", "promoter_bonus_per_order")
    op.drop_column("app_settings", "promoter_program_enabled")

    op.drop_constraint("ck_orders_promoter_bonus_nonneg", "orders", type_="check")
    op.drop_column("orders", "promoter_bonus_amount")
    op.drop_column("orders", "promoter_code")
    op.drop_index("ix_orders_promoter_id", table_name="orders")
    op.drop_constraint("fk_orders_promoter_id_promoters", "orders", type_="foreignkey")
    op.drop_column("orders", "promoter_id")

    op.drop_index(
        "ix_promoter_redemptions_promoter_id", table_name="promoter_redemptions",
    )
    op.drop_index(
        "ix_promoter_redemptions_customer_id", table_name="promoter_redemptions",
    )
    op.drop_table("promoter_redemptions")

    op.drop_index("ix_promoters_deleted_at", table_name="promoters")
    op.drop_index("ix_promoters_promo_code", table_name="promoters")
    op.drop_table("promoters")
