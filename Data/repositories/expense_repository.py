"""ExpenseRepository — rasxodlar, kategoriyalar va doimiy shablonlar.

Uchala jadval bitta aggregate (P&L moduli) bo'lgani uchun bitta repository —
UoW yupqa qoladi. `model = Expense` (asosiy jadval); kategoriya va shablon
metodlari aniq nom bilan ajratilgan.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from Data.repositories.base import BaseRepository
from Domain.models.expense import Expense, ExpenseCategory, RecurringExpense


def _window_filter(since: date, until: date):
    """[since..until] oynasiga TEGISHLI rasxodlar:

      * oddiy yozuv (qamrov davri yo'q) — spent_on oynada;
      * qamrovli yozuv (period_start/period_end) — davr oyna bilan KESISHADI
        (oldindan to'langan oylik keyingi oylarda ham hisobot oynasiga kiradi).
    """
    return or_(
        and_(
            Expense.period_start.is_(None),
            Expense.spent_on >= since,
            Expense.spent_on <= until,
        ),
        and_(
            Expense.period_start.is_not(None),
            Expense.period_start <= until,
            Expense.period_end >= since,
        ),
    )


def _prorated_amount(since: date, until: date):
    """Oyna ichiga to'g'ri keladigan summa ULUSHI (SQL ifodasi).

    Qamrovli yozuv: amount × (oyna∩davr kunlari) / (davr kunlari) — 2 xonaga
    yaxlitlanadi. Oddiy yozuv: to'liq amount (filtr spent_on'ni kafolatlaydi).
    PostgreSQL'da DATE − DATE = butun son (kunlar), shuning uchun +1 bilan
    inklyuziv hisoblanadi.
    """
    overlap_days = (
        func.least(Expense.period_end, until)
        - func.greatest(Expense.period_start, since)
        + 1
    )
    total_days = Expense.period_end - Expense.period_start + 1
    return case(
        (
            Expense.period_start.is_not(None),
            func.round(Expense.amount * overlap_days / total_days, 2),
        ),
        else_=Expense.amount,
    )


class ExpenseRepository(BaseRepository[Expense]):
    model = Expense

    # ---------------------- Kategoriyalar ----------------------

    async def list_categories(self, *, include_archived: bool = False) -> Sequence[ExpenseCategory]:
        stmt = select(ExpenseCategory).order_by(ExpenseCategory.name.asc())
        if not include_archived:
            stmt = stmt.where(ExpenseCategory.deleted_at.is_(None))
        res = await self._session.execute(stmt)
        return res.scalars().all()

    async def get_category(self, category_id: int) -> Optional[ExpenseCategory]:
        return await self._session.get(ExpenseCategory, category_id)

    async def find_category_by_name(self, name: str) -> Optional[ExpenseCategory]:
        """Aktiv kategoriyalar ichida nom bo'yicha (case-insensitive) qidiradi."""
        res = await self._session.execute(
            select(ExpenseCategory).where(
                ExpenseCategory.deleted_at.is_(None),
                func.lower(ExpenseCategory.name) == (name or "").strip().lower(),
            )
        )
        return res.scalar_one_or_none()

    async def add_category(self, category: ExpenseCategory) -> ExpenseCategory:
        self._session.add(category)
        await self._session.flush()
        return category

    # ---------------------- Doimiy shablonlar ----------------------

    async def list_recurring(self, *, include_archived: bool = False) -> Sequence[RecurringExpense]:
        stmt = select(RecurringExpense).order_by(RecurringExpense.id.asc())
        if not include_archived:
            stmt = stmt.where(RecurringExpense.deleted_at.is_(None))
        res = await self._session.execute(stmt)
        return res.scalars().all()

    async def get_recurring(self, recurring_id: int) -> Optional[RecurringExpense]:
        return await self._session.get(RecurringExpense, recurring_id)

    async def add_recurring(self, rec: RecurringExpense) -> RecurringExpense:
        self._session.add(rec)
        await self._session.flush()
        return rec

    # ---------------------- Rasxod yozuvlari ----------------------

    async def list_in_window(
        self,
        since: date,
        until: date,
        *,
        category_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Expense]:
        """[since..until] (ikkalasi ham kiradi) oynasiga tegishli aktiv rasxodlar.

        Qamrovli (oldindan to'langan) yozuvlar davri oyna bilan kesishsa ham
        kiradi — ro'yxatda ko'rinadi, hisobotda esa faqat ulushi hisoblanadi.
        """
        stmt = self._active_only(
            select(Expense)
            .where(_window_filter(since, until))
            .order_by(Expense.spent_on.desc(), Expense.id.desc())
        )
        if category_id is not None:
            stmt = stmt.where(Expense.category_id == category_id)
        res = await self._session.execute(stmt.offset(offset).limit(limit))
        return res.scalars().all()

    async def count_in_window(
        self, since: date, until: date, *, category_id: Optional[int] = None,
    ) -> int:
        stmt = self._active_only(
            select(func.count(Expense.id))
            .where(_window_filter(since, until))
        )
        if category_id is not None:
            stmt = stmt.where(Expense.category_id == category_id)
        res = await self._session.execute(stmt)
        return int(res.scalar_one() or 0)

    async def sum_in_window(self, since: date, until: date) -> Decimal:
        """Davr jami rasxodi — moliya hisobotining `expenses_total`i.

        Qamrovli yozuvlar PROPORTSIONAL hisoblanadi: 6 oyga oldindan to'langan
        oylikning shu oyga faqat 1/6 qismi tushadi ("faqat ishlatilgan rasxod").
        """
        prorated = _prorated_amount(since, until)
        stmt = self._active_only(
            select(func.coalesce(func.sum(prorated), 0))
            .where(_window_filter(since, until))
        )
        res = await self._session.execute(stmt)
        return Decimal(str(res.scalar_one() or 0))

    async def sum_by_category_in_window(
        self, since: date, until: date,
    ) -> list[tuple[int, str, Decimal]]:
        """(category_id, category_name, total) — davr breakdown'i, kamayish tartibida.

        sum_in_window bilan bir xil proportsional taqsimot qo'llanadi.
        """
        prorated = _prorated_amount(since, until)
        total_expr = func.coalesce(func.sum(prorated), 0)
        stmt = (
            select(
                Expense.category_id,
                ExpenseCategory.name,
                total_expr.label("total"),
            )
            .join(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
            .where(
                Expense.deleted_at.is_(None),
                _window_filter(since, until),
            )
            .group_by(Expense.category_id, ExpenseCategory.name)
            .order_by(total_expr.desc())
        )
        res = await self._session.execute(stmt)
        return [(int(r[0]), str(r[1]), Decimal(str(r[2] or 0))) for r in res.all()]

    async def last_materialized_date(self, recurring_id: int) -> Optional[date]:
        """Shablonning eng oxirgi materializatsiya sanasi (high-water mark).

        Soft-delete filtri YO'Q — arxivlangan yozuv ham kalitni band qiladi
        (unique indeks), shuning uchun MAX butun jadval bo'yicha olinadi.
        """
        res = await self._session.execute(
            select(func.max(Expense.spent_on)).where(Expense.recurring_id == recurring_id)
        )
        return res.scalar_one_or_none()

    async def insert_materialized(
        self,
        *,
        recurring_id: int,
        category_id: int,
        amount: Decimal,
        spent_on: date,
        note: str,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
    ) -> bool:
        """Shablondan bitta davr yozuvini IDEMPOTENT yaratadi.

        PostgreSQL `INSERT ... ON CONFLICT DO NOTHING` — partial unique indeks
        (recurring_id, spent_on) bo'yicha; parallel so'rovlarda ham xavfsiz
        (daily_order_counters falsafasi). Qaytaradi: yangi qator yaratildimi.

        `period_start/period_end` — YEARLY shablonlar uchun qamrov davri
        (yillik summa 12 oyga proportsional taqsimlanadi).
        """
        stmt = (
            pg_insert(Expense)
            .values(
                recurring_id=recurring_id,
                category_id=category_id,
                amount=amount,
                spent_on=spent_on,
                note=note,
                created_by=None,
                period_start=period_start,
                period_end=period_end,
            )
            .on_conflict_do_nothing(
                index_elements=["recurring_id", "spent_on"],
                index_where=Expense.recurring_id.is_not(None),
            )
        )
        res = await self._session.execute(stmt)
        return bool(res.rowcount)
