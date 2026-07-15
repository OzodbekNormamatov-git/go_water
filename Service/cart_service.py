"""CartService — Mini App (webapp) server-side savatchasi.

Atomarlik UnitOfWork orqali. Eslatma: mijoz BOTI o'zining FSM (in-memory)
savatchasidan foydalanadi — bu jadval faqat Mini App uchun; ikkalasi
sinxronlanmaydi (bot fallback oqimi mustaqil).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from Data.unit_of_work import UnitOfWork
from Domain.constants import MAX_QUANTITY_PER_ITEM
from Domain.models.cart import CartItem
from Service.exceptions import (
    InvalidOperationError,
    ValidationError,
)


@dataclass(slots=True)
class CartLine:
    food_id: int
    name: str
    price: float
    quantity: int
    image_path: str | None
    line_total: float


@dataclass(slots=True)
class CartView:
    items: List[CartLine]
    total: float
    count: int

    @property
    def is_empty(self) -> bool:
        return not self.items


class CartService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def view(self, telegram_id: int) -> CartView:
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get_by_telegram_id(telegram_id)
            if user is None:
                return CartView(items=[], total=0.0, count=0)
            rows = await uow.carts.list_for_customer(user.id)
            items: List[CartLine] = []
            total = 0.0
            count = 0
            for r in rows:
                if r.food is None or not r.food.is_available:
                    continue
                line_total = float(r.food.price) * r.quantity
                items.append(CartLine(
                    food_id=r.food_id,
                    name=r.food.name,
                    price=float(r.food.price),
                    quantity=r.quantity,
                    image_path=r.food.image_file_id,
                    line_total=line_total,
                ))
                total += line_total
                count += r.quantity
            return CartView(items=items, total=total, count=count)

    async def set_quantity(self, telegram_id: int, food_id: int, quantity: int) -> CartView:
        """Mahsulot miqdorini absolyut o'rnatadi (0 → olib tashlaydi)."""
        if quantity < 0:
            raise ValidationError("cart_item_qty_invalid")
        if quantity > MAX_QUANTITY_PER_ITEM:
            raise ValidationError(
                "cart_item_qty_too_big", context={"max": MAX_QUANTITY_PER_ITEM},
            )
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get_by_telegram_id(telegram_id)
            if user is None:
                raise InvalidOperationError("user_not_registered")
            food = await uow.foods.get(food_id)
            if food is None or not food.is_available:
                raise InvalidOperationError(
                    "food_unavailable", context={"food_id": food_id},
                )
            existing = await uow.carts.get_for_customer_food(user.id, food_id)
            if quantity == 0:
                if existing is not None:
                    await uow.session.delete(existing)
            elif existing is None:
                await uow.carts.add(CartItem(
                    customer_id=user.id, food_id=food_id, quantity=quantity,
                ))
            else:
                existing.quantity = quantity
                await uow.carts.add(existing)
        return await self.view(telegram_id)

    async def clear(self, telegram_id: int) -> None:
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get_by_telegram_id(telegram_id)
            if user is None:
                return
            await uow.carts.clear_for_customer(user.id)
