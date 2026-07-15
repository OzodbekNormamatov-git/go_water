"""OperatorCallRepository — Aqlli eslatma qo'ng'iroqlar jurnali (append-only)."""
from __future__ import annotations

from datetime import date
from typing import Optional, Sequence

from sqlalchemy import func, select

from Data.repositories.base import BaseRepository
from Domain.models.operator_call import OperatorCall


class OperatorCallRepository(BaseRepository[OperatorCall]):
    model = OperatorCall

    async def last_call_per_customer(
        self, customer_ids: Sequence[int],
    ) -> dict[int, OperatorCall]:
        """Har mijozning eng oxirgi qo'ng'irog'i — bitta so'rovda (N+1 yo'q).

        Ro'yxat chegaralangan (yuzlab mijoz), shuning uchun barcha
        mos yozuvlarni olib Python'da birinchisini tanlash yetarli tez.
        """
        if not customer_ids:
            return {}
        res = await self._session.execute(
            select(OperatorCall)
            .where(OperatorCall.customer_id.in_(list(customer_ids)))
            .order_by(OperatorCall.customer_id.asc(), OperatorCall.called_at.desc())
        )
        out: dict[int, OperatorCall] = {}
        for call in res.scalars().all():
            out.setdefault(int(call.customer_id), call)
        return out

    async def snoozed_until_map(self, today: date) -> dict[int, date]:
        """Hozir snooze'da turgan mijozlar: customer_id -> eng katta snooze_until."""
        res = await self._session.execute(
            select(
                OperatorCall.customer_id,
                func.max(OperatorCall.snooze_until),
            )
            .where(OperatorCall.snooze_until.is_not(None), OperatorCall.snooze_until >= today)
            .group_by(OperatorCall.customer_id)
        )
        return {int(cid): until for cid, until in res.all()}

    async def list_for_customer(
        self, customer_id: int, *, limit: int = 20,
    ) -> Sequence[OperatorCall]:
        res = await self._session.execute(
            select(OperatorCall)
            .where(OperatorCall.customer_id == customer_id)
            .order_by(OperatorCall.called_at.desc())
            .limit(limit)
        )
        return res.scalars().all()

    async def last_call_for_customer(self, customer_id: int) -> Optional[OperatorCall]:
        res = await self._session.execute(
            select(OperatorCall)
            .where(OperatorCall.customer_id == customer_id)
            .order_by(OperatorCall.called_at.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()
