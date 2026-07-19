"""Integratsion testlar uchun umumiy SQLite in-memory yordamchi.

Testlar production PostgreSQL o'rniga SQLite ishlatadi — tez va o'rnatishsiz.
DIQQAT: bu Postgres-only konstruksiyalarni (FOR UPDATE qulfi real bloklashi,
ON CONFLICT) TO'LIQ tekshirmaydi — race-stsenariylar uchun alohida Postgres
integratsion muhit kerak (roadmap №4). Bu yerdagi testlar BIZNES-MANTIQ va
LEDGER invariantlarini qoplaydi.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from Domain.models.base import Base
import Domain.models  # noqa: F401 — barcha modellarni mapper'ga ro'yxatlaydi
from Domain.models.app_settings import AppSettings
from Domain.models.courier import Courier
from Domain.models.food import Food
from Domain.models.order import Order, OrderItem
from Domain.models.user import User
from Domain.enums import OrderStatus


async def make_engine() -> tuple[AsyncEngine, async_sessionmaker]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    # Postgres'ga xos greatest/least funksiyalari (rasxod proportsional summary
    # SQL'ida ishlatiladi) — SQLite'da yo'q, testda o'zimiz ro'yxatlaymiz.
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _pg_compat(dbapi_conn, _record):
        dbapi_conn.create_function("greatest", 2, lambda a, b: max(a, b))
        dbapi_conn.create_function("least", 2, lambda a, b: min(a, b))

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    return engine, sf


async def seed_settings(
    sf,
    *,
    cashback_enabled: bool = False,
    cashback_percent: str = "0",
    max_ratio: str = "1.00",
) -> None:
    async with sf() as s:
        await s.merge(AppSettings(
            id=1,
            cashback_enabled=cashback_enabled,
            cashback_percent=Decimal(cashback_percent),
            max_cashback_usage_ratio=Decimal(max_ratio),
        ))
        await s.commit()


async def seed_customer_courier(
    sf,
    *,
    tag: int,
    cashback_balance: str = "0",
    bottles_balance: int = 0,
    deposit_balance: str = "0",
) -> tuple[int, int, int]:
    """(user_id, courier_id, courier_telegram_id) qaytaradi."""
    async with sf() as s:
        u = User(
            telegram_id=1000 + tag, full_name="Test Mijoz",
            phone_number=f"+99890000{tag:04d}",
            cashback_balance=Decimal(cashback_balance),
            deposit_balance=Decimal(deposit_balance),
            bottles_balance=bottles_balance, has_started_bot=True,
        )
        c = Courier(
            telegram_id=2000 + tag, full_name="Test Kuryer",
            is_active=True, has_started_bot=True,
        )
        s.add_all([u, c])
        await s.commit()
        return u.id, c.id, 2000 + tag


async def seed_arrived_order(
    sf,
    *,
    user_id: int,
    courier_id: int,
    unit_price: str = "22000",
    quantity: int = 4,
    cashback_used: str = "0",
    bottles_issued: int | None = None,
    bottles_returned: int = 0,
    payment_method: str = "cash",
) -> tuple[int, list[int]]:
    """ARRIVED holatdagi buyurtma (kuryer eshik oldida) — (order_id, item_ids)."""
    price = Decimal(unit_price)
    items_total = price * quantity
    used = Decimal(cashback_used)
    async with sf() as s:
        o = Order(
            customer_id=user_id, courier_id=courier_id, status=OrderStatus.ARRIVED,
            items_total=items_total, cashback_used=used,
            cashback_earned=Decimal("0"), total_amount=items_total - used,
            payment_method=payment_method,
            bottles_issued=quantity if bottles_issued is None else bottles_issued,
            bottles_returned=bottles_returned,
            delivery_latitude=41.3, delivery_longitude=69.2,
            contact_phone="+998900000000", note="test",
        )
        o.items = [OrderItem(
            food_name="Suv 19L", unit_price=price, unit_cost=Decimal("0"),
            quantity=quantity, bottles_per_unit=1,
        )]
        s.add(o)
        await s.commit()
        return o.id, [i.id for i in o.items]


async def seed_food(sf, *, price: str = "11111.00") -> int:
    async with sf() as s:
        food = Food(name="Suv 19L", price=Decimal(price), is_available=True)
        s.add(food)
        await s.commit()
        return food.id
