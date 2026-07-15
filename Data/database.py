from __future__ import annotations

import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from Domain.models.base import Base

log = logging.getLogger(__name__)

# Idempotent migratsiyalar — mavjud bazaga yangi ustun va jadval qo'shadi.
# Alembic'gacha vaqtinchalik yechim; har bir o'zgarishni shu yerga yozamiz.
# Har biri ALOHIDA tranzaksiyada ishlaydi (Pg'da xato butun blokni bloklamasin).
_MIGRATIONS: tuple[str, ...] = (
    # ------ Eski (asl) idempotent o'zgarishlar ------
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_dm_message_id BIGINT",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivering_at TIMESTAMPTZ",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)",
    "CREATE INDEX IF NOT EXISTS ix_orders_idempotency_key ON orders (idempotency_key)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_customer_id_idempotency_key "
        "ON orders (customer_id, idempotency_key) WHERE idempotency_key IS NOT NULL",
    "ALTER TABLE order_items DROP CONSTRAINT IF EXISTS fk_order_items_food_id_foods",
    "ALTER TABLE order_items ALTER COLUMN food_id DROP NOT NULL",
    """ALTER TABLE order_items
       ADD CONSTRAINT fk_order_items_food_id_foods
       FOREIGN KEY (food_id) REFERENCES foods(id) ON DELETE SET NULL""",

    # ------ v2: Mijoz keshbek + idishlar balansi ------
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS cashback_balance NUMERIC(12,2) NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS bottles_balance INTEGER NOT NULL DEFAULT 0",
    # CHECK constraint'lar — balanslar manfiy bo'lmasligini DB tomonida ham kafolatlaydi.
    """DO $$ BEGIN
       IF NOT EXISTS (
         SELECT 1 FROM pg_constraint WHERE conname = 'ck_users_cashback_nonneg'
       ) THEN
         ALTER TABLE users ADD CONSTRAINT ck_users_cashback_nonneg
           CHECK (cashback_balance >= 0);
       END IF;
       END $$""",
    """DO $$ BEGIN
       IF NOT EXISTS (
         SELECT 1 FROM pg_constraint WHERE conname = 'ck_users_bottles_nonneg'
       ) THEN
         ALTER TABLE users ADD CONSTRAINT ck_users_bottles_nonneg
           CHECK (bottles_balance >= 0);
       END IF;
       END $$""",

    # ------ v2: Buyurtmaga keshbek/bottle/manzil snapshot ustunlari ------
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS items_total NUMERIC(12,2) NOT NULL DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS cashback_used NUMERIC(12,2) NOT NULL DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS cashback_earned NUMERIC(12,2) NOT NULL DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS bottles_issued INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS bottles_returned INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS address_label VARCHAR(40) NOT NULL DEFAULT ''",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS address_details VARCHAR(200) NOT NULL DEFAULT ''",
    # Eski yozuvlarda items_total = total_amount (cashback bo'lmagan), backfill.
    "UPDATE orders SET items_total = total_amount WHERE items_total = 0 AND total_amount > 0",

    # ------ v3: performance indekslari (katta bazada admin paneli tezligi uchun) ------
    # pg_trgm — full_name/phone_number ustida `ilike '%q%'` sequential-scansiz.
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE INDEX IF NOT EXISTS ix_users_full_name_trgm "
        "ON users USING gin (full_name gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS ix_users_phone_trgm "
        "ON users USING gin (phone_number gin_trgm_ops)",
    # Sortlash uchun (ro'yxatlar standart tartibi).
    "CREATE INDEX IF NOT EXISTS ix_users_created_at_desc ON users (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_orders_created_at_desc ON orders (created_at DESC)",
    # Status filter + sort kombinatsiyasi uchun composite indeks.
    "CREATE INDEX IF NOT EXISTS ix_orders_status_created_at ON orders (status, created_at DESC)",
    # Kuryer DELIVERED statistikasi uchun partial indeks.
    "CREATE INDEX IF NOT EXISTS ix_orders_delivered_at "
        "ON orders (delivered_at DESC) WHERE delivered_at IS NOT NULL",
    # Default manzilni tezda topish uchun partial indeks.
    "CREATE INDEX IF NOT EXISTS ix_customer_addresses_default "
        "ON customer_addresses (customer_id) WHERE is_default = true",

    # ------ v4: app_settings singleton + default qator ------
    """CREATE TABLE IF NOT EXISTS app_settings (
        id INTEGER PRIMARY KEY,
        cashback_enabled BOOLEAN NOT NULL DEFAULT true,
        cashback_percent NUMERIC(5,2) NOT NULL DEFAULT 1.5,
        max_cashback_usage_ratio NUMERIC(5,2) NOT NULL DEFAULT 1.00,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    # Singleton qatorni yaratamiz (id=1) — har sozlama o'qiganda chaqiriladi.
    "INSERT INTO app_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING",

    # ------ v5: broadcast'larda ixtiyoriy rasm ------
    "ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS photo_path VARCHAR(255)",

    # ------ v6: Soft delete — 4 ta jadval ------
    "ALTER TABLE foods    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
    "ALTER TABLE users    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
    "ALTER TABLE couriers ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
    "ALTER TABLE orders   ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
    # Partial indekslar — faqat aktiv qatorlar uchun.
    # Bu eng tez-tez ishlatiladigan filter (WHERE deleted_at IS NULL),
    # kichik indeks katta jadvalda ham millisekundlar javob beradi.
    "CREATE INDEX IF NOT EXISTS ix_foods_active "
        "ON foods (id) WHERE deleted_at IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_users_active "
        "ON users (id) WHERE deleted_at IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_couriers_active "
        "ON couriers (id) WHERE deleted_at IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_orders_active "
        "ON orders (id) WHERE deleted_at IS NULL",

    # ------ v7: ARRIVED status + arrival notification message + arrived_at timestamp ------
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_arrived_message_id BIGINT",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS arrived_at TIMESTAMPTZ",

    # ------ v8: Call operator order creation ------
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_by_operator_id BIGINT",
    "CREATE INDEX IF NOT EXISTS ix_orders_created_by_operator_id "
        "ON orders (created_by_operator_id) WHERE created_by_operator_id IS NOT NULL",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS has_started_bot BOOLEAN NOT NULL DEFAULT false",
    # Eski (existing) mijozlar ro'yxatdan o'tgan bo'lsa, ular bot bilan
    # ishlagan — bizning yangi flagimiz default false, lekin ular allaqachon
    # /start bosgan. Backfill: barcha mavjud mijozlarni True deb belgilaymiz.
    # Yangi (operator yaratgan) mijozlar default false bo'lib qoladi.
    "UPDATE users SET has_started_bot = true WHERE has_started_bot = false AND telegram_id > 0",

    # ------ v9: Kuryer telefon raqami ------
    # NULL: hali kiritilmagan (eski kuryerlar). Mijoz va admin ko'radi.
    "ALTER TABLE couriers ADD COLUMN IF NOT EXISTS phone_number VARCHAR(20)",

    # ------ v10: Kunlik buyurtma raqami ------
    # Order.daily_number — har kuni 1 dan boshlanadigan, odamlar ko'radigan raqam.
    # NULL: eski buyurtmalar (display'da #id ga fallback).
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS daily_number INTEGER",
    # Atomik counter jadval — har kun bitta qator (Toshkent sanasi).
    """CREATE TABLE IF NOT EXISTS daily_order_counters (
        day DATE PRIMARY KEY,
        last_number INTEGER NOT NULL DEFAULT 0
    )""",

    # (v11 raqami ishlatilmaydi — global min_order_quantity g'oyasi v13'dagi
    #  per-mahsulot `foods.min_quantity` bilan almashtirilgan.)

    # ------ v12: Kuryer naqd pul balansi ------
    # Courier.cash_balance — kuryer qo'lidagi naqd (DELIVERED'da += total_amount).
    "ALTER TABLE couriers ADD COLUMN IF NOT EXISTS cash_balance NUMERIC(12,2) NOT NULL DEFAULT 0",
    # CHECK — naqd balans manfiy bo'lmasin (settle balansdan oshmaydi).
    """DO $$ BEGIN
       IF NOT EXISTS (
         SELECT 1 FROM pg_constraint WHERE conname = 'ck_couriers_cash_nonneg'
       ) THEN
         ALTER TABLE couriers ADD CONSTRAINT ck_couriers_cash_nonneg
           CHECK (cash_balance >= 0);
       END IF;
       END $$""",

    # ------ v13: Per-mahsulot minimal buyurtma soni ------
    # Food.min_quantity — mahsulot bo'yicha minimal dona (default 1 = cheklov yo'q).
    "ALTER TABLE foods ADD COLUMN IF NOT EXISTS min_quantity INTEGER NOT NULL DEFAULT 1",
    # Global min_order_quantity bekor qilindi — per-mahsulot min bilan almashtirildi.
    "ALTER TABLE app_settings DROP COLUMN IF EXISTS min_order_quantity",

    # ------ v14: Sanaladigan/sanalmaydigan tovarlar (qaytariladigan idishlar) ------
    # Food.bottles_per_unit — har dona necha qaytariladigan idish beradi
    # (0 = sanalmaydi: pumpa/kuller/filtr; 1 = oddiy idish; N = multi-pack).
    "ALTER TABLE foods ADD COLUMN IF NOT EXISTS bottles_per_unit SMALLINT NOT NULL DEFAULT 1",
    # order_items.bottles_per_unit — buyurtma vaqtidagi qiymat SNAPSHOT'i.
    "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS bottles_per_unit SMALLINT NOT NULL DEFAULT 1",

    # ------ v15: Append-only moliyaviy jurnal (ledger_entries) ------
    # Jadval va indekslar `Base.metadata.create_all` tomonidan yaratiladi
    # (model ro'yxatdan o'tgan). Bu yerda faqat mavjud balanslarni BACKFILL
    # qilamiz — har nolga teng bo'lmagan balans uchun bitta opening_balance
    # seed yozuvi. NOT EXISTS bilan idempotent (har startda xavfsiz qayta ishlaydi).
    """INSERT INTO ledger_entries
        (subject_type, subject_id, account, kind, delta, balance_after, reason, created_at)
       SELECT 'user', id, 'cashback', 'opening_balance',
              cashback_balance, cashback_balance, 'Ochilish balansi (ledger joriy etildi)', NOW()
       FROM users
       WHERE cashback_balance <> 0
         AND NOT EXISTS (SELECT 1 FROM ledger_entries le
            WHERE le.subject_type='user' AND le.subject_id=users.id AND le.account='cashback')""",
    """INSERT INTO ledger_entries
        (subject_type, subject_id, account, kind, delta, balance_after, reason, created_at)
       SELECT 'user', id, 'bottles', 'opening_balance',
              bottles_balance, bottles_balance, 'Ochilish balansi (ledger joriy etildi)', NOW()
       FROM users
       WHERE bottles_balance <> 0
         AND NOT EXISTS (SELECT 1 FROM ledger_entries le
            WHERE le.subject_type='user' AND le.subject_id=users.id AND le.account='bottles')""",
    """INSERT INTO ledger_entries
        (subject_type, subject_id, account, kind, delta, balance_after, reason, created_at)
       SELECT 'courier', id, 'cash', 'opening_balance',
              cash_balance, cash_balance, 'Ochilish balansi (ledger joriy etildi)', NOW()
       FROM couriers
       WHERE cash_balance <> 0
         AND NOT EXISTS (SELECT 1 FROM ledger_entries le
            WHERE le.subject_type='courier' AND le.subject_id=couriers.id AND le.account='cash')""",

    # ------ v16: Avto-eslatma (predictive reorder) ------
    # Sozlama ustunlari (reminders jadvali `create_all` orqali yaratiladi).
    "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS reminders_enabled BOOLEAN NOT NULL DEFAULT true",
    "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS reminder_lead_days INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS reminders_enabled BOOLEAN NOT NULL DEFAULT true",

    # ------ v17: Ko'p telefon raqam (user_phones) ------
    # Jadval `create_all` orqali yaratiladi. Bu yerda BACKFILL: har mavjud
    # mijozning `phone_number` (primary kesh) qiymati user_phones'ga primary
    # qator sifatida ko'chiriladi. NOT EXISTS bilan idempotent.
    """INSERT INTO user_phones (user_id, phone, is_primary, label, created_at, updated_at)
       SELECT u.id, u.phone_number, true, NULL, NOW(), NOW()
       FROM users u
       WHERE u.phone_number IS NOT NULL AND u.phone_number <> ''
         AND NOT EXISTS (SELECT 1 FROM user_phones p WHERE p.phone = u.phone_number)""",

    # ------ v17: Mahsulot tannarxi (COGS) — moliya foyda hisobi uchun ------
    # `Food.cost_price` — admin kiritadi; `order_items.unit_cost` — buyurtma
    # paytidagi SNAPSHOT (unit_price naqshi). Eski qatorlarda 0 (noma'lum).
    "ALTER TABLE foods ADD COLUMN IF NOT EXISTS cost_price NUMERIC(12,2) NOT NULL DEFAULT 0",
    "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS unit_cost NUMERIC(12,2) NOT NULL DEFAULT 0",

    # ------ v17: Aqlli eslatma sozlamasi ------
    # OVERDUE → CHURNED chegarasi (kunlarda); operator_calls jadvali create_all'da.
    # Ustun v18'da radar_churn_after_days -> reorder_churn_after_days ga o'zgardi.
    "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS reorder_churn_after_days INTEGER NOT NULL DEFAULT 14",

    # ------ v18: Kuryer yetkazgan haqiqiy dona (delivered_quantity) ------
    # order_items.delivered_quantity — kuryer yetkazishda o'zgartirsa (mijoz
    # 4 o'rniga 6 olsa) shu yoziladi; NULL = o'zgartirmagan (= buyurtilgan).
    # Pul/idish/foyda hisobi COALESCE(delivered_quantity, quantity) dan olinadi.
    "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS delivered_quantity INTEGER",

    # ------ v18: "radar" -> "aqlli eslatma" nomlash tozalashi ------
    # v1.2.0'da radar_churn_after_days deb qo'shilgan bo'lsa — reorder'ga
    # ko'chiramiz (eski qiymatni saqlab), so'ng eski ustunni tashlaymiz.
    # DO-blok: fresh o'rnatishda ustun yo'q — shartli tekshiruv har bootda
    # "Migration skipped" shovqinini oldini oladi.
    """DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='app_settings' AND column_name='radar_churn_after_days') THEN
            UPDATE app_settings SET reorder_churn_after_days = radar_churn_after_days
            WHERE radar_churn_after_days IS NOT NULL;
        END IF;
    END $$""",
    "ALTER TABLE app_settings DROP COLUMN IF EXISTS radar_churn_after_days",

    # ------ v19: Depozit balans (MChJ avans) + to'lov usuli + operatorlar ------
    # users.deposit_balance — oldindan to'lov balansi; CHECK >= 0 (cash_balance naqshi).
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS deposit_balance NUMERIC(12,2) NOT NULL DEFAULT 0",
    """DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='ck_users_deposit_nonneg') THEN
            ALTER TABLE users ADD CONSTRAINT ck_users_deposit_nonneg CHECK (deposit_balance >= 0);
        END IF;
    END $$""",
    # orders.payment_method — cash|card|deposit (VARCHAR; default = eski xulq).
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(16) NOT NULL DEFAULT 'cash'",
    # operators jadvali `create_all` orqali yaratiladi (Domain/models/operator.py).

    # ------ v19: Rasxod qamrov davri (oldindan to'langan oylik va h.k.) ------
    # Hisobot summani [period_start..period_end] kunlariga proportsional
    # taqsimlaydi — har oyga faqat o'sha oyning ulushi kiradi.
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS period_start DATE",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS period_end DATE",
    """DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='ck_expenses_period_valid') THEN
            ALTER TABLE expenses ADD CONSTRAINT ck_expenses_period_valid CHECK (
                (period_start IS NULL AND period_end IS NULL) OR
                (period_start IS NOT NULL AND period_end IS NOT NULL AND period_end >= period_start)
            );
        END IF;
    END $$""",

    # ------ v19: Telefon +998 backfill ------
    # '+' + 9 raqam (998'siz saqlangan) → '+998...'. UNIQUE to'qnashuvda
    # (ikkala forma alohida yozuv) qator tegilmaydi — qo'lda merge kerak.
    r"""UPDATE users u SET phone_number = '+998' || substr(phone_number, 2)
       WHERE phone_number ~ '^\+\d{9}$'
         AND NOT EXISTS (SELECT 1 FROM users u2
            WHERE u2.phone_number = '+998' || substr(u.phone_number, 2))""",
    r"""UPDATE user_phones p SET phone = '+998' || substr(phone, 2)
       WHERE phone ~ '^\+\d{9}$'
         AND NOT EXISTS (SELECT 1 FROM user_phones p2
            WHERE p2.phone = '+998' || substr(p.phone, 2))""",
    r"""UPDATE couriers SET phone_number = '+998' || substr(phone_number, 2)
       WHERE phone_number ~ '^\+\d{9}$'""",
    r"""UPDATE orders SET contact_phone = '+998' || substr(contact_phone, 2)
       WHERE contact_phone ~ '^\+\d{9}$'""",

    # ------ v19: recurring_expenses.period enum-nom tozalashi ------
    # ORM enum NOMlarni saqlaydi ('MONTHLY'); kichik harfli qiymat (eski
    # server_default'dan) barcha o'qishlarni sindirardi — normallashtiramiz.
    "UPDATE recurring_expenses SET period = UPPER(period) "
        "WHERE period IN ('monthly', 'weekly', 'yearly')",
)


class Database:
    """Async SQLAlchemy engine + session factory'ni inkapsulyatsiya qiluvchi sinf."""

    def __init__(self, url: str, echo: bool = False) -> None:
        self._engine: AsyncEngine = create_async_engine(
            url,
            echo=echo,
            pool_pre_ping=True,
            future=True,
        )
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self._engine,
            expire_on_commit=False,
            autoflush=False,
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    async def create_all(self) -> None:
        """MVP uchun jadvallarni yaratadi. Prodda Alembic migratsiyalardan foydalanish kerak.

        `create_all` mavjud jadvallarga yangi ustun qo'shmaydi — shu sababli
        idempotent ALTER TABLE / DROP CONSTRAINT qatorlarini yuritamiz.

        Har bir migratsiya **alohida tranzaksiyada** ishlaydi — bittasi
        muvaffaqiyatsiz bo'lsa, qolganlari to'sib qolmaydi (PostgreSQL
        bitta tranzaksiyada xato bo'lsa, keyingi statementlar bloklanadi).
        """
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        for stmt in _MIGRATIONS:
            try:
                async with self._engine.begin() as conn:
                    await conn.execute(text(stmt))
            except Exception as e:
                log.warning("Migration skipped (%s): %s", stmt.splitlines()[0][:80], e)

    async def dispose(self) -> None:
        await self._engine.dispose()
