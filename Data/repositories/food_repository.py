from __future__ import annotations

from typing import Sequence

from sqlalchemy import func, select

from Data.repositories.base import BaseRepository
from Domain.models.food import Food


class FoodRepository(BaseRepository[Food]):
    model = Food

    async def list_available(self) -> Sequence[Food]:
        """Mijoz uchun: faqat aktiv (deleted_at IS NULL) va is_available=True."""
        stmt = self._active_only(
            select(Food).where(Food.is_available.is_(True)).order_by(Food.name)
        )
        res = await self._session.execute(stmt)
        return res.scalars().all()

    async def list_all_ordered(self) -> Sequence[Food]:
        """Admin uchun: aktiv mahsulotlar (is_available farqi yo'q).
        Arxivlangan mahsulotlar `list_archived` orqali olinadi.
        """
        stmt = self._active_only(select(Food).order_by(Food.name))
        res = await self._session.execute(stmt)
        return res.scalars().all()

    async def list_archived(self) -> Sequence[Food]:
        """Admin "Arxiv" tab uchun — faqat soft-deleted mahsulotlar."""
        stmt = self._deleted_only(select(Food).order_by(Food.deleted_at.desc()))
        res = await self._session.execute(stmt)
        return res.scalars().all()

    # ---------------------- Paginated (admin large lists) ----------------------

    async def list_paginated(
        self, *, archived: bool = False, limit: int = 50, offset: int = 0,
    ) -> Sequence[Food]:
        """Paginatsiyalangan ro'yxat — `archived=True` Arxiv tab uchun."""
        base = select(Food)
        if archived:
            stmt = self._deleted_only(base).order_by(Food.deleted_at.desc())
        else:
            stmt = self._active_only(base).order_by(Food.name)
        stmt = stmt.offset(offset).limit(limit)
        res = await self._session.execute(stmt)
        return res.scalars().all()

    async def count(self, *, archived: bool = False) -> int:
        base = select(func.count(Food.id))
        stmt = self._deleted_only(base) if archived else self._active_only(base)
        res = await self._session.execute(stmt)
        return int(res.scalar_one() or 0)
