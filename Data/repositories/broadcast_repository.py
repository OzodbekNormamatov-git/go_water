from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import func, select

from Data.repositories.base import BaseRepository
from Domain.models.broadcast import Broadcast, BroadcastStatus


class BroadcastRepository(BaseRepository[Broadcast]):
    model = Broadcast

    async def list_recent(self, limit: int = 30) -> Sequence[Broadcast]:
        res = await self._session.execute(
            select(Broadcast).order_by(Broadcast.created_at.desc()).limit(limit)
        )
        return res.scalars().all()

    async def get_active(self) -> Optional[Broadcast]:
        """Hozir yuborilayotgan rassilkani topadi (atomarlik uchun bittaginasi aktiv bo'lishi shart)."""
        res = await self._session.execute(
            select(Broadcast).where(Broadcast.status == BroadcastStatus.SENDING).limit(1)
        )
        return res.scalar_one_or_none()

    # ---------------------- Paginated (admin large lists) ----------------------

    async def list_paginated(
        self, *, limit: int = 50, offset: int = 0,
    ) -> Sequence[Broadcast]:
        """Paginatsiyalangan rassilkalar — yangilari yuqorida."""
        stmt = (
            select(Broadcast)
            .order_by(Broadcast.created_at.desc())
            .offset(offset).limit(limit)
        )
        res = await self._session.execute(stmt)
        return res.scalars().all()

    async def count(self) -> int:
        res = await self._session.execute(select(func.count(Broadcast.id)))
        return int(res.scalar_one() or 0)
