from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from Data.unit_of_work import UnitOfWork
from Domain.constants import MAX_BOTTLES_PER_UNIT, MAX_QUANTITY_PER_ITEM
from Domain.models.food import Food
from Service.exceptions import EntityNotFoundError, ValidationError


def _coerce_price(value) -> Decimal:
    try:
        price = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValidationError("price_invalid")
    if price <= 0:
        raise ValidationError("price_positive")
    return price.quantize(Decimal("0.01"))


def _coerce_cost_price(value) -> Decimal:
    """Tannarx — 0 ruxsat (kiritilmagan = foyda hisobida "noma'lum")."""
    try:
        cost = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValidationError("cost_price_invalid")
    if cost < 0:
        raise ValidationError("cost_price_negative")
    return cost.quantize(Decimal("0.01"))


def _coerce_min_quantity(value) -> int:
    """Per-mahsulot minimal buyurtma soni — 1..MAX_QUANTITY_PER_ITEM oralig'ida.

    Noto'g'ri qiymat (matn, manfiy, 0, juda katta) — ValidationError.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValidationError(
            "food_min_qty_invalid",
            context={"min": 1, "max": MAX_QUANTITY_PER_ITEM},
        )
    if n < 1 or n > MAX_QUANTITY_PER_ITEM:
        raise ValidationError(
            "food_min_qty_invalid",
            context={"min": 1, "max": MAX_QUANTITY_PER_ITEM},
        )
    return n


def _coerce_bottles_per_unit(value) -> int:
    """Har dona qaytariladigan idishlar soni — 0..MAX_BOTTLES_PER_UNIT.

    0 = sanalmaydi (pumpa/kuller/filtr), 1 = oddiy idish, N = multi-pack.
    Noto'g'ri qiymat (matn, manfiy, juda katta) — ValidationError.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValidationError(
            "food_bottles_per_unit_invalid",
            context={"min": 0, "max": MAX_BOTTLES_PER_UNIT},
        )
    if n < 0 or n > MAX_BOTTLES_PER_UNIT:
        raise ValidationError(
            "food_bottles_per_unit_invalid",
            context={"min": 0, "max": MAX_BOTTLES_PER_UNIT},
        )
    return n


class FoodService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def list_menu(self) -> Sequence[Food]:
        """Mijoz uchun — faqat aktiv + sotuvda mavjud."""
        async with UnitOfWork(self._sf) as uow:
            return await uow.foods.list_available()

    async def list_all(self) -> Sequence[Food]:
        """Admin uchun — aktiv mahsulotlar (arxivlanganlar `list_archived`'da)."""
        async with UnitOfWork(self._sf) as uow:
            return await uow.foods.list_all_ordered()

    async def list_archived(self) -> Sequence[Food]:
        """Admin "Arxiv" tab — soft-deleted mahsulotlar."""
        async with UnitOfWork(self._sf) as uow:
            return await uow.foods.list_archived()

    async def list_paginated(
        self, *, archived: bool = False, limit: int = 50, offset: int = 0,
    ) -> tuple[Sequence[Food], int]:
        """Admin uchun: paginatsiyalangan ro'yxat + total — bitta UoW ichida."""
        async with UnitOfWork(self._sf) as uow:
            total = await uow.foods.count(archived=archived)
            items = await uow.foods.list_paginated(
                archived=archived, limit=limit, offset=offset,
            )
            return items, total

    async def get(self, food_id: int) -> Food:
        async with UnitOfWork(self._sf) as uow:
            food = await uow.foods.get(food_id)
            if food is None:
                raise EntityNotFoundError("food_not_found")
            return food

    async def create(
        self,
        *,
        name: str,
        description: str,
        price,
        image_file_id: Optional[str],
        cost_price=0,
        min_quantity: int = 1,
        bottles_per_unit: int = 1,
    ) -> Food:
        name = (name or "").strip()
        if len(name) < 2:
            raise ValidationError("name_short")
        price_dec = _coerce_price(price)
        cost_dec = _coerce_cost_price(cost_price)
        min_q = _coerce_min_quantity(min_quantity)
        bpu = _coerce_bottles_per_unit(bottles_per_unit)
        async with UnitOfWork(self._sf) as uow:
            food = Food(
                name=name,
                description=(description or "").strip(),
                price=price_dec,
                cost_price=cost_dec,
                min_quantity=min_q,
                bottles_per_unit=bpu,
                image_file_id=image_file_id,
                is_available=True,
            )
            return await uow.foods.add(food)

    async def update(
        self,
        food_id: int,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        price=None,
        cost_price=None,
        image_file_id: Optional[str] = None,
        is_available: Optional[bool] = None,
        min_quantity: Optional[int] = None,
        bottles_per_unit: Optional[int] = None,
    ) -> Food:
        async with UnitOfWork(self._sf) as uow:
            food = await uow.foods.get(food_id)
            if food is None:
                raise EntityNotFoundError("food_not_found")
            if name is not None:
                name = name.strip()
                if len(name) < 2:
                    raise ValidationError("name_short")
                food.name = name
            if description is not None:
                food.description = description.strip()
            if price is not None:
                food.price = _coerce_price(price)
            if cost_price is not None:
                food.cost_price = _coerce_cost_price(cost_price)
            if image_file_id is not None:
                # Bo'sh string (rasm o'chirildi) — DB'da NULL bo'lsin (toza semantika).
                food.image_file_id = image_file_id or None
            if is_available is not None:
                food.is_available = is_available
            if min_quantity is not None:
                food.min_quantity = _coerce_min_quantity(min_quantity)
            if bottles_per_unit is not None:
                food.bottles_per_unit = _coerce_bottles_per_unit(bottles_per_unit)
            try:
                await uow.foods.add(food)
            except StaleDataError:
                # Get va flush orasida boshqa admin/sessiya mahsulotni o'chirgan
                # (yoki UI eski keshdan stale id yuborgan). 500 emas, 404 qaytamiz.
                raise EntityNotFoundError("food_not_found")
            return food

    async def delete(self, food_id: int) -> None:
        """SOFT DELETE — mahsulotni arxivga ko'chiradi (deleted_at = NOW()).

        Tarix saqlanadi: eski buyurtmalarda mahsulot avvalgidek ko'rinadi.
        Admin "Arxiv" tab'idan `restore()` orqali qaytarish mumkin.
        Idempotent — ikki marta chaqirilsa ham xato yo'q.
        """
        async with UnitOfWork(self._sf) as uow:
            food = await uow.foods.get(food_id)
            if food is None or food.is_deleted:
                # Allaqachon yo'q yoki arxivlangan — idempotent muvaffaqiyat
                return
            await uow.foods.soft_delete(food)

    async def restore(self, food_id: int) -> Food:
        """Arxivlangan mahsulotni qaytaradi (admin "Arxiv" tab uchun)."""
        async with UnitOfWork(self._sf) as uow:
            food = await uow.foods.get(food_id)
            if food is None:
                raise EntityNotFoundError("food_not_found")
            if not food.is_deleted:
                return food  # Allaqachon aktiv — idempotent
            return await uow.foods.restore(food)

    async def purge(self, food_id: int) -> None:
        """HARD DELETE — qatorni butunlay o'chiradi (faqat tozalash ishlari uchun).

        DIQQAT: order_items.food_id NULL bo'ladi (ON DELETE SET NULL), lekin
        food_name/unit_price snapshot saqlanadi. Bu metod admin UI'da yo'q —
        faqat maxsus tozalash skriptlari uchun.
        """
        async with UnitOfWork(self._sf) as uow:
            food = await uow.foods.get(food_id)
            if food is None:
                return
            try:
                await uow.foods.delete(food)
            except StaleDataError:
                return
