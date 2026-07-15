from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import func, select

from Data.repositories.base import BaseRepository
from Domain.models.operator import Operator


class OperatorRepository(BaseRepository[Operator]):
    model = Operator

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[Operator]:
        """Soft-deleted bo'lsa ham qaytaradi — restore va audit uchun."""
        res = await self._session.execute(
            select(Operator).where(Operator.telegram_id == telegram_id)
        )
        return res.scalar_one_or_none()

    async def is_active_operator(self, telegram_id: int) -> bool:
        """Admin bot gate'i uchun tez tekshiruv: aktiv operatormi.

        FAQAT is_active — arxivlash tushunchasi operatorlarda YO'Q (egasi
        talabi: aktiv/noaktiv yetarli). Eski deleted_at qiymatlari e'tiborga
        olinmaydi — aks holda tarixan arxivlangan operator "Aktivlashtirish"
        bosilsa ham kira olmay qolardi (ko'rinmas blok).
        """
        res = await self._session.execute(
            select(Operator.id).where(
                Operator.telegram_id == telegram_id,
                Operator.is_active.is_(True),
            )
        )
        return res.scalar_one_or_none() is not None

    async def list_paginated(
        self, *, limit: int = 50, offset: int = 0,
    ) -> Sequence[Operator]:
        """Paginatsiyalangan ro'yxat — BARCHA operatorlar (avval aktivlar).

        deleted_at filtri YO'Q: arxivlash olib tashlangan; tarixan arxivlangan
        qatorlar ham ko'rinadi (noaktiv sifatida boshqariladi).
        """
        stmt = (
            select(Operator)
            .order_by(Operator.is_active.desc(), Operator.full_name.asc())
            .offset(offset).limit(limit)
        )
        res = await self._session.execute(stmt)
        return res.scalars().all()

    async def count(self) -> int:
        res = await self._session.execute(select(func.count(Operator.id)))
        return int(res.scalar_one() or 0)
