"""LedgerRepository — append-only moliyaviy jurnal kirishi.

Faqat INSERT va SELECT — UPDATE/DELETE yo'q (immutable jurnal). Balansni
hisoblash/tekshirish uchun SUM(delta) ham shu yerda.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import func, select

from Data.repositories.base import BaseRepository
from Domain.models.ledger import LedgerEntry


class LedgerRepository(BaseRepository[LedgerEntry]):
    model = LedgerEntry

    async def get_by_idempotency_key(
        self, subject_type: str, subject_id: int, account: str, key: str,
    ) -> Optional[LedgerEntry]:
        """Idempotency — shu kalit bilan oldin yozilgan bo'lsa, o'shani qaytaradi."""
        stmt = select(LedgerEntry).where(
            LedgerEntry.subject_type == subject_type,
            LedgerEntry.subject_id == subject_id,
            LedgerEntry.account == account,
            LedgerEntry.idempotency_key == key,
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_for_subject(
        self,
        subject_type: str,
        subject_id: int,
        *,
        account: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[LedgerEntry]:
        """Subyekt hisobining tarixini eng yangi birinchi tartibda qaytaradi."""
        stmt = select(LedgerEntry).where(
            LedgerEntry.subject_type == subject_type,
            LedgerEntry.subject_id == subject_id,
        )
        if account is not None:
            stmt = stmt.where(LedgerEntry.account == account)
        stmt = stmt.order_by(LedgerEntry.id.desc()).limit(limit).offset(offset)
        res = await self._session.execute(stmt)
        return res.scalars().all()

    async def count_for_subject(
        self, subject_type: str, subject_id: int, *, account: Optional[str] = None,
    ) -> int:
        stmt = select(func.count(LedgerEntry.id)).where(
            LedgerEntry.subject_type == subject_type,
            LedgerEntry.subject_id == subject_id,
        )
        if account is not None:
            stmt = stmt.where(LedgerEntry.account == account)
        res = await self._session.execute(stmt)
        return int(res.scalar_one() or 0)

    async def computed_balance(
        self, subject_type: str, subject_id: int, account: str,
    ) -> Decimal:
        """Jurnal'dan balansni qayta hisoblaydi (SUM(delta)) — tekshirish/tuzatish uchun."""
        stmt = select(func.coalesce(func.sum(LedgerEntry.delta), 0)).where(
            LedgerEntry.subject_type == subject_type,
            LedgerEntry.subject_id == subject_id,
            LedgerEntry.account == account,
        )
        res = await self._session.execute(stmt)
        return Decimal(str(res.scalar_one() or 0))
