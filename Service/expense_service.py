"""ExpenseService — kompaniya rasxodlari (P&L moduli).

Uch qatlam:
  * Kategoriyalar — kengayuvchan ro'yxat (ijara, oylik, benzin...), soft-delete.
  * Doimiy shablonlar (`recurring_expenses`) — "har oyning 1-sanasi 3 mln ijara".
  * Konkret yozuvlar (`expenses`) — hisobot FAQAT shulardan o'qiydi.

MATERIALIZATSIYA (kelishilgan best practice): doimiy shablon har davr uchun
alohida `expenses` qatorini yaratadi — tahrirlanadigan, auditlanadigan.
`ensure_materialized(today)` idempotent (UNIQUE(recurring_id, spent_on) +
ON CONFLICT DO NOTHING) va har hisobot/ro'yxat so'rovida arzon chaqiriladi —
alohida scheduler shart emas (bitta-jarayon arxitekturasiga mos).

Davr sanalari generatsiyasi — sof funksiyalar (reminder_math falsafasi):
yon ta'sirsiz, oson test qilinadi.
"""
from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from Data.unit_of_work import UnitOfWork
from Domain.constants import EXPENSE_MATERIALIZE_LOOKBACK_DAYS
from Domain.models.expense import (
    Expense,
    ExpenseCategory,
    ExpensePeriod,
    RecurringExpense,
)
from Service.exceptions import (
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)

log = logging.getLogger(__name__)


def local_today() -> date:
    """Mahalliy (Toshkent yoki config'dagi) "bugun" — server tz'idan mustaqil.

    Rasxod sanalari mahalliy semantikada (analytics/lifecycle bilan bir xil):
    server UTC bo'lsa ham 1-sana anchor'li rasxod mahalliy yarim tunda yoziladi.
    """
    try:
        from config import get_settings
        return datetime.now(ZoneInfo(get_settings().timezone)).date()
    except Exception:
        return datetime.now(timezone(timedelta(hours=5))).date()


# ---------------------- Sof funksiyalar (davr generatsiyasi) ----------------------

def clamp_day_to_month(year: int, month: int, day: int) -> date:
    """31-sana fevralda 28/29 ga tushadi — oy oxiriga clamp."""
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(max(1, day), last))


def occurrences_between(
    period: ExpensePeriod,
    anchor_day: int,
    anchor_month: Optional[int],
    start: date,
    end_incl: date,
) -> List[date]:
    """Shablonning [start..end_incl] oralig'idagi barcha davr sanalari.

    MONTHLY: har oyda `anchor_day` (qisqa oyda oy oxiri).
    WEEKLY:  har hafta `anchor_day` kuni (0=Dushanba .. 6=Yakshanba).
    YEARLY:  har yili `anchor_month`/`anchor_day`.
    """
    if end_incl < start:
        return []
    out: List[date] = []
    if period == ExpensePeriod.WEEKLY:
        wd = anchor_day % 7
        # start'dan keyingi birinchi mos hafta kuni
        d = start + timedelta(days=(wd - start.weekday()) % 7)
        while d <= end_incl:
            out.append(d)
            d += timedelta(days=7)
    elif period == ExpensePeriod.MONTHLY:
        y, m = start.year, start.month
        while True:
            occ = clamp_day_to_month(y, m, anchor_day)
            if occ > end_incl:
                break
            if occ >= start:
                out.append(occ)
            m += 1
            if m > 12:
                m, y = 1, y + 1
    else:  # YEARLY
        am = anchor_month or 1
        for y in range(start.year, end_incl.year + 1):
            occ = clamp_day_to_month(y, am, anchor_day)
            if start <= occ <= end_incl:
                out.append(occ)
    return out


def _coerce_amount(value) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValidationError("expense_amount_invalid")
    if amount <= 0:
        raise ValidationError("expense_amount_positive")
    return amount.quantize(Decimal("0.01"))


def _validate_period_range(
    period_start: Optional[date], period_end: Optional[date],
) -> None:
    """Qamrov davri: ikkalasi birga NULL yoki birga to'ldirilgan, end >= start.

    Maksimal 5 yil — xato terilgan sana (masalan 2062) hisobotni yillar davomida
    "sudrab yurishining" oldini oladi.
    """
    if (period_start is None) != (period_end is None):
        raise ValidationError("expense_dates_invalid")
    if period_start is not None and period_end is not None:
        if period_end < period_start:
            raise ValidationError("expense_dates_invalid")
        if (period_end - period_start).days > 5 * 366:
            raise ValidationError("expense_dates_invalid")


def _add_year_minus_day(d: date) -> date:
    """d + 1 yil − 1 kun (29-fevral xavfsiz) — yillik qamrov davrining oxiri."""
    try:
        nxt = date(d.year + 1, d.month, d.day)
    except ValueError:  # 29-fevral
        nxt = date(d.year + 1, d.month, 28)
    return nxt - timedelta(days=1)


def _validate_anchor(period: ExpensePeriod, anchor_day: int, anchor_month: Optional[int]) -> None:
    if period == ExpensePeriod.WEEKLY:
        if not (0 <= anchor_day <= 6):
            raise ValidationError("expense_anchor_day_invalid", context={"min": 0, "max": 6})
    else:
        if not (1 <= anchor_day <= 31):
            raise ValidationError("expense_anchor_day_invalid", context={"min": 1, "max": 31})
    if period == ExpensePeriod.YEARLY:
        if anchor_month is None or not (1 <= int(anchor_month) <= 12):
            raise ValidationError("expense_anchor_month_invalid", context={"min": 1, "max": 12})


# ---------------------- DTO ----------------------

@dataclass(slots=True)
class ExpenseSummary:
    """Davr rasxod xulosasi — moliya hisobotiga qo'shiladi."""
    total: Decimal
    by_category: List[tuple[int, str, Decimal]]  # (category_id, name, total)


class ExpenseService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ---------------------- Kategoriyalar ----------------------

    async def list_categories(self, *, include_archived: bool = False) -> Sequence[ExpenseCategory]:
        async with UnitOfWork(self._sf) as uow:
            return await uow.expenses.list_categories(include_archived=include_archived)

    async def create_category(self, name: str) -> ExpenseCategory:
        name = (name or "").strip()
        if len(name) < 2:
            raise ValidationError("name_short")
        async with UnitOfWork(self._sf) as uow:
            existing = await uow.expenses.find_category_by_name(name)
            if existing is not None:
                # Idempotent — bir xil nom bilan dublikat yaratilmaydi.
                return existing
            return await uow.expenses.add_category(ExpenseCategory(name=name))

    async def rename_category(self, category_id: int, name: str) -> ExpenseCategory:
        name = (name or "").strip()
        if len(name) < 2:
            raise ValidationError("name_short")
        async with UnitOfWork(self._sf) as uow:
            cat = await uow.expenses.get_category(category_id)
            if cat is None:
                raise EntityNotFoundError("expense_category_not_found")
            dup = await uow.expenses.find_category_by_name(name)
            if dup is not None and dup.id != category_id:
                raise InvalidOperationError("expense_category_name_taken")
            cat.name = name
            uow.session.add(cat)
            return cat

    async def archive_category(self, category_id: int) -> None:
        """Soft-delete. Yozuvlar/shablonlar FK bilan qoladi (tarix buzilmaydi);
        aktiv doimiy shablon bo'lsa — avval uni to'xtatish talab qilinadi."""
        async with UnitOfWork(self._sf) as uow:
            cat = await uow.expenses.get_category(category_id)
            if cat is None or cat.is_deleted:
                return
            recs = await uow.expenses.list_recurring(include_archived=False)
            if any(r.category_id == category_id for r in recs):
                raise InvalidOperationError("expense_category_has_recurring")
            cat.deleted_at = datetime.now(timezone.utc)
            uow.session.add(cat)

    async def restore_category(self, category_id: int) -> ExpenseCategory:
        async with UnitOfWork(self._sf) as uow:
            cat = await uow.expenses.get_category(category_id)
            if cat is None:
                raise EntityNotFoundError("expense_category_not_found")
            if cat.is_deleted:
                # Arxivdaligida bir xil nomli yangi kategoriya yaratilgan
                # bo'lishi mumkin — ikkita aktiv dublikatga yo'l qo'ymaymiz.
                dup = await uow.expenses.find_category_by_name(cat.name)
                if dup is not None and dup.id != category_id:
                    raise InvalidOperationError("expense_category_name_taken")
                cat.deleted_at = None
                uow.session.add(cat)
            return cat

    # ---------------------- Doimiy shablonlar ----------------------

    async def list_recurring(self, *, include_archived: bool = False) -> Sequence[RecurringExpense]:
        async with UnitOfWork(self._sf) as uow:
            return await uow.expenses.list_recurring(include_archived=include_archived)

    async def create_recurring(
        self,
        *,
        category_id: int,
        label: str,
        amount,
        period: str = "monthly",
        anchor_day: int = 1,
        anchor_month: Optional[int] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> RecurringExpense:
        try:
            per = ExpensePeriod(period)
        except ValueError:
            raise ValidationError("expense_period_invalid")
        amount_dec = _coerce_amount(amount)
        _validate_anchor(per, int(anchor_day), anchor_month)
        start = start_date or local_today()
        if end_date is not None and end_date < start:
            raise ValidationError("expense_dates_invalid")
        async with UnitOfWork(self._sf) as uow:
            cat = await uow.expenses.get_category(category_id)
            if cat is None or cat.is_deleted:
                raise EntityNotFoundError("expense_category_not_found")
            rec = RecurringExpense(
                category_id=category_id,
                label=(label or "").strip()[:120],
                amount=amount_dec,
                period=per,
                anchor_day=int(anchor_day),
                anchor_month=int(anchor_month) if anchor_month is not None else None,
                start_date=start,
                end_date=end_date,
            )
            rec = await uow.expenses.add_recurring(rec)
            # MUHIM: relationship'ni sessiya yopilishidan OLDIN to'ldiramiz —
            # aks holda route serializer'i (`r.category.name`) detached
            # instance'da lazy-load qilib DetachedInstanceError → 500 berardi.
            rec.category = cat
            return rec

    async def update_recurring(
        self,
        recurring_id: int,
        *,
        label: Optional[str] = None,
        amount=None,
        end_date: Optional[date] = None,
        clear_end_date: bool = False,
    ) -> RecurringExpense:
        """Shablonni yangilaydi. MUHIM: `amount` o'zgarishi faqat KELAJAK
        davrlarga ta'sir qiladi — allaqachon materializatsiya qilingan yozuvlar
        o'zgarmaydi (ularni alohida tahrirlash mumkin — auditlanadigan model)."""
        async with UnitOfWork(self._sf) as uow:
            rec = await uow.expenses.get_recurring(recurring_id)
            if rec is None or rec.is_deleted:
                raise EntityNotFoundError("expense_recurring_not_found")
            if label is not None:
                rec.label = label.strip()[:120]
            if amount is not None:
                rec.amount = _coerce_amount(amount)
            if clear_end_date:
                rec.end_date = None
            elif end_date is not None:
                # start_date'dan oldingi end_date — shablon jimgina "o'lik"
                # bo'lib qolardi (davr generatsiyasi bo'sh) — aniq xato beramiz.
                if end_date < rec.start_date:
                    raise ValidationError("expense_dates_invalid")
                rec.end_date = end_date
            uow.session.add(rec)
            return rec

    async def archive_recurring(self, recurring_id: int) -> None:
        """Shablonni to'xtatadi (soft-delete) — yangi davrlar yaratilmaydi,
        mavjud materializatsiya qilingan yozuvlar qoladi."""
        async with UnitOfWork(self._sf) as uow:
            rec = await uow.expenses.get_recurring(recurring_id)
            if rec is None or rec.is_deleted:
                return
            rec.deleted_at = datetime.now(timezone.utc)
            uow.session.add(rec)

    async def ensure_materialized(self, upto: Optional[date] = None) -> int:
        """Barcha aktiv shablonlarning [start..min(upto,end)] davr yozuvlarini
        yaratadi. IDEMPOTENT (ON CONFLICT DO NOTHING) — har chaqiruv xavfsiz.

        Qaytaradi: yangi yaratilgan yozuvlar soni.
        """
        today = upto or local_today()
        # Himoya: juda eski start_date ming-minglab qator yaratmasin.
        floor = today - timedelta(days=EXPENSE_MATERIALIZE_LOOKBACK_DAYS)
        created = 0
        async with UnitOfWork(self._sf) as uow:
            recs = await uow.expenses.list_recurring(include_archived=False)
            for rec in recs:
                start = max(rec.start_date, floor)
                # High-water mark: allaqachon yozilgan davrlarni qayta
                # generatsiya qilmaymiz — har so'rovda faqat YANGI sanalar
                # INSERT bo'ladi (idempotentlik unique indeksda baribir bor,
                # bu faqat keraksiz statement'larni olib tashlaydi).
                hwm = await uow.expenses.last_materialized_date(rec.id)
                if hwm is not None and hwm + timedelta(days=1) > start:
                    start = hwm + timedelta(days=1)
                end = min(today, rec.end_date) if rec.end_date else today
                for occ in occurrences_between(
                    rec.period, int(rec.anchor_day), rec.anchor_month, start, end,
                ):
                    note = rec.label or "Doimiy rasxod"
                    # YEARLY: yillik summa 12 oyga proportsional taqsimlanadi —
                    # qamrov davri [occ .. occ+1yil−1kun]. Aks holda butun yillik
                    # to'lov bitta oyning hisobotiga tushib, foydani buzardi.
                    p_start = p_end = None
                    if rec.period == ExpensePeriod.YEARLY:
                        p_start, p_end = occ, _add_year_minus_day(occ)
                    if await uow.expenses.insert_materialized(
                        recurring_id=rec.id,
                        category_id=rec.category_id,
                        amount=Decimal(rec.amount),
                        spent_on=occ,
                        note=note,
                        period_start=p_start,
                        period_end=p_end,
                    ):
                        created += 1
        if created:
            log.info("Doimiy rasxodlar materializatsiyasi: %s ta yangi yozuv", created)
        return created

    # ---------------------- Konkret yozuvlar ----------------------

    async def add_expense(
        self,
        *,
        category_id: int,
        amount,
        spent_on: date,
        note: str = "",
        created_by: Optional[int] = None,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
    ) -> Expense:
        """Yangi rasxod. `period_start/period_end` (ixtiyoriy) — oldindan
        to'langan rasxodning qamrov davri: hisobot summani davr kunlariga
        proportsional taqsimlaydi (masalan, 6 oylik oylik → har oyga 1/6)."""
        amount_dec = _coerce_amount(amount)
        _validate_period_range(period_start, period_end)
        async with UnitOfWork(self._sf) as uow:
            cat = await uow.expenses.get_category(category_id)
            if cat is None or cat.is_deleted:
                raise EntityNotFoundError("expense_category_not_found")
            exp = Expense(
                category_id=category_id,
                amount=amount_dec,
                spent_on=spent_on,
                note=(note or "").strip()[:255],
                created_by=created_by,
                period_start=period_start,
                period_end=period_end,
            )
            exp = await uow.expenses.add(exp)
            # MUHIM (BUG FIX): relationship'ni sessiya yopilishidan OLDIN
            # to'ldiramiz. Avval route serializer'i (`e.category.name`) commit +
            # close'dan keyingi detached instance'da lazy-load qilib
            # DetachedInstanceError → 500 berardi (yozuv esa DB'ga tushib
            # bo'lgan — har retry jimgina dublikat yaratardi).
            exp.category = cat
            return exp

    async def update_expense(
        self,
        expense_id: int,
        *,
        amount=None,
        spent_on: Optional[date] = None,
        note: Optional[str] = None,
        category_id: Optional[int] = None,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
        clear_period: bool = False,
    ) -> Expense:
        """Yozuvni tahrirlash — materializatsiya qilingan (masalan, bir oy ijara
        oshgan) yozuvni ham alohida o'zgartirish mumkin (kelishilgan model).
        Eslatma: materializatsiyalangan yozuvning `spent_on`i o'zgartirilmaydi —
        u idempotentlik kaliti (recurring_id, spent_on) qismi.

        `clear_period=True` — qamrov davrini olib tashlaydi (oddiy rasxodga
        qaytaradi); aks holda period juftligi berilsa yangilanadi."""
        async with UnitOfWork(self._sf) as uow:
            exp = await uow.expenses.get(expense_id)
            if exp is None or exp.is_deleted:
                raise EntityNotFoundError("expense_not_found")
            if amount is not None:
                exp.amount = _coerce_amount(amount)
            if spent_on is not None:
                if exp.recurring_id is not None and spent_on != exp.spent_on:
                    raise InvalidOperationError("expense_recurring_date_locked")
                exp.spent_on = spent_on
            if note is not None:
                exp.note = note.strip()[:255]
            if category_id is not None:
                cat = await uow.expenses.get_category(category_id)
                if cat is None or cat.is_deleted:
                    raise EntityNotFoundError("expense_category_not_found")
                exp.category_id = category_id
            if clear_period:
                exp.period_start = None
                exp.period_end = None
            elif period_start is not None or period_end is not None:
                # Juftlik to'liq berilishi shart (yarim yangilash chalkash).
                new_start = period_start if period_start is not None else exp.period_start
                new_end = period_end if period_end is not None else exp.period_end
                _validate_period_range(new_start, new_end)
                exp.period_start = new_start
                exp.period_end = new_end
            uow.session.add(exp)
            return exp

    async def archive_expense(self, expense_id: int) -> None:
        """Soft-delete — hisobotdan chiqadi, audit tarixi qoladi.

        DIQQAT: materializatsiyalangan yozuv arxivlansa, idempotentlik kaliti
        (unique indeks) band qoladi — shu davr qayta yaratilmaydi. Bu ataylab:
        "bu oy ijara to'lanmadi" holati uchun to'g'ri semantika."""
        async with UnitOfWork(self._sf) as uow:
            exp = await uow.expenses.get(expense_id)
            if exp is None or exp.is_deleted:
                return
            await uow.expenses.soft_delete(exp)

    async def list_expenses(
        self,
        since: date,
        until: date,
        *,
        category_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[Expense], int]:
        """Davr yozuvlari + jami soni. Avval materializatsiya (idempotent)."""
        await self.ensure_materialized(min(until, local_today()))
        async with UnitOfWork(self._sf) as uow:
            total = await uow.expenses.count_in_window(since, until, category_id=category_id)
            items = await uow.expenses.list_in_window(
                since, until, category_id=category_id, limit=limit, offset=offset,
            )
            return items, total

    async def summary(self, since: date, until: date) -> ExpenseSummary:
        """Davr xulosasi (jami + kategoriya breakdown) — moliya hisoboti uchun."""
        await self.ensure_materialized(min(until, local_today()))
        async with UnitOfWork(self._sf) as uow:
            total = await uow.expenses.sum_in_window(since, until)
            by_cat = await uow.expenses.sum_by_category_in_window(since, until)
            return ExpenseSummary(total=total, by_category=by_cat)
