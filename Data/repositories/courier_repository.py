from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import func, select

from Data.repositories.base import BaseRepository
from Domain.models.courier import Courier


class CourierRepository(BaseRepository[Courier]):
    model = Courier

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[Courier]:
        """Soft-deleted bo'lsa ham qaytaradi — admin restore va eski buyurtmalar uchun."""
        res = await self._session.execute(
            select(Courier).where(Courier.telegram_id == telegram_id)
        )
        return res.scalar_one_or_none()

    async def get_for_update(self, courier_id: int) -> Optional[Courier]:
        """Pessimistic row-lock — naqd balansni atomik yangilash uchun (settle).

        populate_existing — instans shu sessiyada avvalroq LOCKsiz yuklangan
        bo'lsa (masalan get_by_telegram_id yoki Order.courier selectinload),
        atributlar lock paytidagi HAQIQIY qiymatga yangilanadi (stale balans
        bilan hisoblash — lost update — oldini oladi).

        YOZISH-TO'SIG'I: avval flush — populate_existing qayta o'qishi
        sessiyadagi flush qilinmagan o'zgarishlarni (Courier.orders selectin
        zanjiri orqali) eski qiymat bilan yo'q qilib yubormasin."""
        await self._session.flush()
        res = await self._session.execute(
            select(Courier).where(Courier.id == courier_id).with_for_update()
            .execution_options(populate_existing=True)
        )
        return res.scalar_one_or_none()

    async def total_cash_outstanding(self) -> tuple[float, int]:
        """Barcha (aktiv) kuryerlar qo'lidagi jami naqd + naqdi bor kuryerlar soni."""
        stmt = self._active_only(
            select(
                func.coalesce(func.sum(Courier.cash_balance), 0),
                func.count(Courier.id),
            ).where(Courier.cash_balance > 0)
        )
        res = await self._session.execute(stmt)
        row = res.first()
        return float(row[0] or 0), int(row[1] or 0)

    async def list_active_started_telegram_ids(self) -> list[int]:
        """Aktiv + botda /start qilgan kuryerlarning telegram_id'lari — yangi
        buyurtma DM bildirishnomasi uchun (web app'ni ochuvchi tugma bilan)."""
        stmt = self._active_only(
            select(Courier.telegram_id).where(
                Courier.is_active.is_(True),
                Courier.has_started_bot.is_(True),
            )
        )
        res = await self._session.execute(stmt)
        return [int(t) for t in res.scalars().all()]

    async def list_all_ordered(self) -> Sequence[Courier]:
        """Admin uchun: avval aktivlar, keyin ism bo'yicha. Faqat soft-active."""
        stmt = self._active_only(
            select(Courier).order_by(Courier.is_active.desc(), Courier.full_name.asc())
        )
        res = await self._session.execute(stmt)
        return res.scalars().all()

    async def list_archived(self) -> Sequence[Courier]:
        """Arxivlangan kuryerlar — admin "Arxiv" tab uchun."""
        stmt = self._deleted_only(select(Courier).order_by(Courier.deleted_at.desc()))
        res = await self._session.execute(stmt)
        return res.scalars().all()

    # ---------------------- Paginated (admin large lists) ----------------------

    async def list_paginated(
        self, *, archived: bool = False, limit: int = 50, offset: int = 0,
    ) -> Sequence[Courier]:
        """Paginatsiyalangan ro'yxat — `archived=True` Arxiv tab uchun."""
        base = select(Courier)
        if archived:
            stmt = self._deleted_only(base).order_by(Courier.deleted_at.desc())
        else:
            stmt = self._active_only(base).order_by(
                Courier.is_active.desc(), Courier.full_name.asc(),
            )
        stmt = stmt.offset(offset).limit(limit)
        res = await self._session.execute(stmt)
        return res.scalars().all()

    async def count(self, *, archived: bool = False) -> int:
        base = select(func.count(Courier.id))
        stmt = self._deleted_only(base) if archived else self._active_only(base)
        res = await self._session.execute(stmt)
        return int(res.scalar_one() or 0)
