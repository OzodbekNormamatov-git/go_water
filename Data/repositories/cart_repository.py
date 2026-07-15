from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from Data.repositories.base import BaseRepository
from Domain.models.cart import CartItem


class CartRepository(BaseRepository[CartItem]):
    model = CartItem

    async def list_for_customer(self, customer_id: int) -> Sequence[CartItem]:
        res = await self._session.execute(
            select(CartItem)
            .where(CartItem.customer_id == customer_id)
            .options(selectinload(CartItem.food))
            .order_by(CartItem.id.asc())
        )
        return res.scalars().all()

    async def get_for_customer_food(
        self, customer_id: int, food_id: int,
    ) -> Optional[CartItem]:
        res = await self._session.execute(
            select(CartItem).where(
                CartItem.customer_id == customer_id,
                CartItem.food_id == food_id,
            )
        )
        return res.scalar_one_or_none()

    async def clear_for_customer(self, customer_id: int) -> int:
        res = await self._session.execute(
            delete(CartItem).where(CartItem.customer_id == customer_id)
        )
        return res.rowcount or 0
