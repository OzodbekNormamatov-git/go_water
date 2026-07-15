"""AnalyticsService — admin uchun moliyaviy hisobotlar va mijozlar faolligi.

Bu service `OrderRepository`/`UserRepository` ustidagi sof aggregator.
Vaqt zonalari Toshkent (yoki config'dan) bo'yicha ishlanadi va UTC
oraliqlariga aylantiriladi — DB qatlamida UTC tartibi saqlanadi.

DAROMAD ASOSI (kassa printsipi): faqat DELIVERED buyurtmalar, delivered_at
oynasi bo'yicha — pul haqiqatda qo'lga tekkan payt. Hali yetkazilmagan yoki
bekor bo'lgan buyurtmalar daromadga kirmaydi.

Moliyaviy breakdown:
  * **total_revenue**   — jami tushum (naqd + karta + balans)
  * **cash_revenue**    — naqd (kuryer orqali yig'ilgan)
  * **card_revenue**    — karta orqali to'langan
  * **deposit_revenue** — mijoz avans (depozit) balansidan yechilgan
  * **cashback_used**   — keshbek bilan qoplangan summa
  * **cashback_earned** — yangi yaratilgan liability
  * **gross_sale**      — items_total (sotuvning umumiy summasi)
  * **cogs**            — sotilgan mahsulot tannarxi (Σ unit_cost × qty snapshot)
  * **gross_profit**    — total_revenue − cogs (savdo marjasi)
  * **expenses_total**  — davr rasxodlari (qamrovli rasxodlar proportsional)
  * **net_profit**      — gross_profit − expenses_total (sof foyda)
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from Data.unit_of_work import UnitOfWork
from Service.timeutil import local_tz as _local_tz, local_tz_name


def _local_to_utc(d_local: datetime) -> datetime:
    return d_local.astimezone(timezone.utc)


def _month_bounds_utc(year: int, month: int) -> Tuple[datetime, datetime]:
    tz = _local_tz()
    start_local = datetime(year, month, 1, 0, 0, 0, tzinfo=tz)
    if month == 12:
        end_local = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=tz)
    else:
        end_local = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=tz)
    return _local_to_utc(start_local), _local_to_utc(end_local)


def _year_bounds_utc(year: int) -> Tuple[datetime, datetime]:
    tz = _local_tz()
    start_local = datetime(year, 1, 1, 0, 0, 0, tzinfo=tz)
    end_local = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=tz)
    return _local_to_utc(start_local), _local_to_utc(end_local)


@dataclass(slots=True)
class DayPoint:
    date: str       # YYYY-MM-DD (local)
    cash_revenue: float
    cashback_used: float
    cashback_earned: float
    gross_sale: float
    count: int
    total_revenue: float = 0.0
    card_revenue: float = 0.0
    deposit_revenue: float = 0.0


@dataclass(slots=True)
class MonthPoint:
    month: str
    cash_revenue: float
    cashback_used: float
    cashback_earned: float
    gross_sale: float
    count: int
    total_revenue: float = 0.0
    card_revenue: float = 0.0
    deposit_revenue: float = 0.0


@dataclass(slots=True)
class ExpenseCategoryPoint:
    """Davr rasxodining bitta kategoriya bo'yicha yig'indisi."""
    category_id: int
    name: str
    total: float


@dataclass(slots=True)
class MonthlyReport:
    year: int
    month: int
    cash_revenue: float
    cashback_used: float
    cashback_earned: float
    gross_sale: float
    total_orders: int
    average_order: float
    days: List[DayPoint]
    # ---- To'lov usuli kesimi ----
    total_revenue: float = 0.0
    card_revenue: float = 0.0
    deposit_revenue: float = 0.0
    # ---- Sof foyda bloki (COGS + rasxodlar) ----
    cogs: float = 0.0
    gross_profit: float = 0.0
    expenses_total: float = 0.0
    net_profit: float = 0.0
    expenses_by_category: List[ExpenseCategoryPoint] = field(default_factory=list)


@dataclass(slots=True)
class YearlyReport:
    year: int
    cash_revenue: float
    cashback_used: float
    cashback_earned: float
    gross_sale: float
    total_orders: int
    average_order: float
    months: List[MonthPoint]
    # ---- To'lov usuli kesimi ----
    total_revenue: float = 0.0
    card_revenue: float = 0.0
    deposit_revenue: float = 0.0
    # ---- Sof foyda bloki (COGS + rasxodlar) ----
    cogs: float = 0.0
    gross_profit: float = 0.0
    expenses_total: float = 0.0
    net_profit: float = 0.0
    expenses_by_category: List[ExpenseCategoryPoint] = field(default_factory=list)


@dataclass(slots=True)
class HourPoint:
    hour: int
    count: int


@dataclass(slots=True)
class WeekdayPoint:
    weekday: int
    count: int


@dataclass(slots=True)
class ActivityReport:
    since: str
    until: str
    signups_by_day: List[Tuple[str, int]]
    customers_total: int
    peak_hours: List[HourPoint]
    peak_weekday: List[WeekdayPoint]
    peak_hour: Optional[int]
    peak_weekday_index: Optional[int]


@dataclass(slots=True)
class CashbackOverview:
    """Cashback dasturining yakuniy moliyaviy hisoboti."""
    config_enabled: bool
    config_percent: float
    config_max_usage_ratio: float
    liability_total: float          # SUM(users.cashback_balance) — qarz
    customers_with_balance: int
    cashback_used_all_time: float   # tarixiy "to'langan" jami
    cashback_earned_all_time: float # tarixiy "berilgan" jami
    bottles_outstanding_total: int
    customers_with_bottles: int


class AnalyticsService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        expense_service=None,
    ) -> None:
        """`expense_service` (ExpenseService) — sof foyda blokini yoqadi.

        None bo'lsa hisobotlar rasxodsiz ishlaydi (soddalashtirilgan test/
        boshqa kontekstlar uchun; production'da main.py doim uzatadi).
        """
        self._sf = session_factory
        self._expenses = expense_service

    async def _profit_block(
        self, since: datetime, until: datetime,
        exp_since: date, exp_until: date,
        total_revenue: float,
    ) -> tuple[float, float, float, float, List[ExpenseCategoryPoint]]:
        """(cogs, gross_profit, expenses_total, net_profit, by_category).

        Foyda JAMI tushum (naqd+karta+balans) asosida — to'lov usuli foydaga
        ta'sir qilmaydi, faqat pul qayerdan kelganini ko'rsatadi.
        """
        async with UnitOfWork(self._sf) as uow:
            cogs = await uow.orders.cogs_in_window(since, until)
        expenses_total = 0.0
        by_cat: List[ExpenseCategoryPoint] = []
        if self._expenses is not None:
            summary = await self._expenses.summary(exp_since, exp_until)
            expenses_total = float(summary.total)
            by_cat = [
                ExpenseCategoryPoint(category_id=cid, name=name, total=float(total))
                for cid, name, total in summary.by_category
            ]
        gross_profit = total_revenue - cogs
        net_profit = gross_profit - expenses_total
        return cogs, gross_profit, expenses_total, net_profit, by_cat

    # ---------------------- Finance ----------------------

    async def monthly_report(self, year: int, month: int) -> MonthlyReport:
        since, until = _month_bounds_utc(year, month)
        tz_name = local_tz_name()
        async with UnitOfWork(self._sf) as uow:
            agg = await uow.orders.finance_in_window(since, until)
            day_rows = await uow.orders.finance_by_day_since(since, tz_name=tz_name)

        existing = {row["date"]: row for row in day_rows}
        last_day = calendar.monthrange(year, month)[1]
        filled: List[DayPoint] = []
        for d in range(1, last_day + 1):
            iso = f"{year:04d}-{month:02d}-{d:02d}"
            row = existing.get(iso, {})
            filled.append(DayPoint(
                date=iso,
                total_revenue=float(row.get("total_revenue", 0)),
                cash_revenue=float(row.get("cash_revenue", 0)),
                card_revenue=float(row.get("card_revenue", 0)),
                deposit_revenue=float(row.get("deposit_revenue", 0)),
                cashback_used=float(row.get("cashback_used", 0)),
                cashback_earned=float(row.get("cashback_earned", 0)),
                gross_sale=float(row.get("gross_sale", 0)),
                count=int(row.get("count", 0)),
            ))
        avg = (agg["total_revenue"] / agg["orders_count"]) if agg["orders_count"] else 0.0
        # Rasxod davri — mahalliy oy chegaralari (spent_on mahalliy sana).
        cogs, gross_profit, expenses_total, net_profit, by_cat = await self._profit_block(
            since, until,
            date(year, month, 1), date(year, month, last_day),
            agg["total_revenue"],
        )
        return MonthlyReport(
            year=year, month=month,
            total_revenue=agg["total_revenue"],
            cash_revenue=agg["cash_revenue"],
            card_revenue=agg["card_revenue"],
            deposit_revenue=agg["deposit_revenue"],
            cashback_used=agg["cashback_used"],
            cashback_earned=agg["cashback_earned"],
            gross_sale=agg["gross_sale"],
            total_orders=agg["orders_count"],
            average_order=avg,
            days=filled,
            cogs=cogs,
            gross_profit=gross_profit,
            expenses_total=expenses_total,
            net_profit=net_profit,
            expenses_by_category=by_cat,
        )

    async def yearly_report(self, year: int) -> YearlyReport:
        since, until = _year_bounds_utc(year)
        tz_name = local_tz_name()
        async with UnitOfWork(self._sf) as uow:
            agg = await uow.orders.finance_in_window(since, until)
            month_rows = await uow.orders.finance_by_month_since(since, tz_name=tz_name)
        existing = {row["month"]: row for row in month_rows}
        filled: List[MonthPoint] = []
        for m in range(1, 13):
            key = f"{year:04d}-{m:02d}"
            row = existing.get(key, {})
            filled.append(MonthPoint(
                month=key,
                total_revenue=float(row.get("total_revenue", 0)),
                cash_revenue=float(row.get("cash_revenue", 0)),
                card_revenue=float(row.get("card_revenue", 0)),
                deposit_revenue=float(row.get("deposit_revenue", 0)),
                cashback_used=float(row.get("cashback_used", 0)),
                cashback_earned=float(row.get("cashback_earned", 0)),
                gross_sale=float(row.get("gross_sale", 0)),
                count=int(row.get("count", 0)),
            ))
        avg = (agg["total_revenue"] / agg["orders_count"]) if agg["orders_count"] else 0.0
        cogs, gross_profit, expenses_total, net_profit, by_cat = await self._profit_block(
            since, until,
            date(year, 1, 1), date(year, 12, 31),
            agg["total_revenue"],
        )
        return YearlyReport(
            year=year,
            total_revenue=agg["total_revenue"],
            cash_revenue=agg["cash_revenue"],
            card_revenue=agg["card_revenue"],
            deposit_revenue=agg["deposit_revenue"],
            cashback_used=agg["cashback_used"],
            cashback_earned=agg["cashback_earned"],
            gross_sale=agg["gross_sale"],
            total_orders=agg["orders_count"],
            average_order=avg,
            months=filled,
            cogs=cogs,
            gross_profit=gross_profit,
            expenses_total=expenses_total,
            net_profit=net_profit,
            expenses_by_category=by_cat,
        )

    # ---------------------- Activity & peak ----------------------

    async def activity_report(self, days: int = 30) -> ActivityReport:
        if days <= 0:
            days = 30
        if days > 365:
            days = 365
        tz = _local_tz()
        today_local = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        since_local = today_local - timedelta(days=days - 1)
        until_local = today_local + timedelta(days=1)
        since = _local_to_utc(since_local)
        until = _local_to_utc(until_local)

        async with UnitOfWork(self._sf) as uow:
            signups = await uow.users.signups_by_day_since(since)
            total_customers = await uow.users.count_all()
            hour_rows = await uow.orders.hourly_counts_in_window(since, until)
            weekday_rows = await uow.orders.weekday_counts_in_window(since, until)

        existing_sign = {d: c for (d, c) in signups}
        filled_signups: List[Tuple[str, int]] = []
        for i in range(days):
            d = (since_local + timedelta(days=i)).date().isoformat()
            filled_signups.append((d, existing_sign.get(d, 0)))

        hour_map = {h: c for (h, c) in hour_rows}
        peak_hours = [HourPoint(hour=h, count=hour_map.get(h, 0)) for h in range(24)]
        peak_hour = max(peak_hours, key=lambda x: x.count).hour if any(x.count for x in peak_hours) else None

        wd_map = {w: c for (w, c) in weekday_rows}
        peak_weekday = [WeekdayPoint(weekday=w, count=wd_map.get(w, 0)) for w in range(7)]
        peak_weekday_index = (
            max(peak_weekday, key=lambda x: x.count).weekday
            if any(x.count for x in peak_weekday) else None
        )

        return ActivityReport(
            since=since_local.date().isoformat(),
            until=until_local.date().isoformat(),
            signups_by_day=filled_signups,
            customers_total=int(total_customers),
            peak_hours=peak_hours,
            peak_weekday=peak_weekday,
            peak_hour=peak_hour,
            peak_weekday_index=peak_weekday_index,
        )

    # ---------------------- Cashback program overview ----------------------

    async def cashback_overview(self) -> CashbackOverview:
        """Cashback dasturining to'liq moliyaviy ko'rinishi — admin uchun.

        Bu — production'da rahbar har kuni qarayotgan ko'rsatkichlar:
          * Liability total — mijozlar qo'lidagi keshbek (kompaniya qarzi)
          * All-time used/earned — dastur boshlanganidan jami
          * Bottles outstanding — qaytarilishi kutilayotgan idishlar
        """
        async with UnitOfWork(self._sf) as uow:
            cfg = await uow.settings.get_or_create()
            liab, with_balance = await uow.users.cashback_liability_total()
            bottles, with_bottles = await uow.users.bottles_outstanding_total()
            totals = await uow.orders.all_time_cashback_totals()
        return CashbackOverview(
            config_enabled=bool(cfg.cashback_enabled),
            config_percent=float(cfg.cashback_percent or 0),
            config_max_usage_ratio=float(cfg.max_cashback_usage_ratio or 0),
            liability_total=liab,
            customers_with_balance=with_balance,
            cashback_used_all_time=float(totals["cashback_used_total"]),
            cashback_earned_all_time=float(totals["cashback_earned_total"]),
            bottles_outstanding_total=bottles,
            customers_with_bottles=with_bottles,
        )
