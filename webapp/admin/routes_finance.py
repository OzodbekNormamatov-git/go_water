"""Admin uchun moliyaviy hisobotlar va mijozlar faolligi.

Bu modul ikki marshrut to'plamini eksport qiladi:
  * `router`            — /api/admin/finance/...  (oylik / yillik)
  * `activity_router`   — /api/admin/activity     (mijoz o'sishi, pik vaqtlar)

Har bir hisobot CASH va CASHBACK metricalarni ALOHIDA ko'rsatadi —
rahbar naqd tushgan summasini keshbek hisobidan qaytadan farqlay olsin.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from Service.analytics_service import AnalyticsService
from webapp.admin.auth import admin_required
from webapp.deps import get_analytics_service

router = APIRouter(prefix="/api/admin/finance", tags=["admin:finance"])


# ---------------------- Schemas ----------------------

class DayPointOut(BaseModel):
    date: str
    cash_revenue: float
    cashback_used: float
    cashback_earned: float
    gross_sale: float
    count: int
    total_revenue: float = 0.0
    card_revenue: float = 0.0
    deposit_revenue: float = 0.0


class MonthPointOut(BaseModel):
    month: str
    cash_revenue: float
    cashback_used: float
    cashback_earned: float
    gross_sale: float
    count: int
    total_revenue: float = 0.0
    card_revenue: float = 0.0
    deposit_revenue: float = 0.0


class ExpenseCategoryPointOut(BaseModel):
    category_id: int
    name: str
    total: float


class MonthlyOut(BaseModel):
    year: int
    month: int
    cash_revenue: float
    cashback_used: float
    cashback_earned: float
    gross_sale: float
    total_orders: int
    average_order: float
    days: List[DayPointOut]
    # To'lov usuli kesimi (daromad = faqat DELIVERED buyurtmalar).
    total_revenue: float = 0.0
    card_revenue: float = 0.0
    deposit_revenue: float = 0.0
    # Sof foyda bloki: COGS (tannarx snapshot) + davr rasxodlari.
    cogs: float = 0.0
    gross_profit: float = 0.0
    expenses_total: float = 0.0
    net_profit: float = 0.0
    expenses_by_category: List[ExpenseCategoryPointOut] = []


class YearlyOut(BaseModel):
    year: int
    cash_revenue: float
    cashback_used: float
    cashback_earned: float
    gross_sale: float
    total_orders: int
    average_order: float
    months: List[MonthPointOut]
    total_revenue: float = 0.0
    card_revenue: float = 0.0
    deposit_revenue: float = 0.0
    cogs: float = 0.0
    gross_profit: float = 0.0
    expenses_total: float = 0.0
    net_profit: float = 0.0
    expenses_by_category: List[ExpenseCategoryPointOut] = []


# ---------------------- Endpoints ----------------------

def _default_year_month() -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    return now.year, now.month


@router.get("/monthly", response_model=MonthlyOut)
async def monthly_report(
    _=Depends(admin_required),
    year: Optional[int] = Query(default=None, ge=2000, le=2100),
    month: Optional[int] = Query(default=None, ge=1, le=12),
    analytics: AnalyticsService = Depends(get_analytics_service),
) -> MonthlyOut:
    y, m = _default_year_month()
    if year is None: year = y
    if month is None: month = m
    rep = await analytics.monthly_report(year=year, month=month)
    return MonthlyOut(
        year=rep.year, month=rep.month,
        total_revenue=rep.total_revenue,
        cash_revenue=rep.cash_revenue,
        card_revenue=rep.card_revenue,
        deposit_revenue=rep.deposit_revenue,
        cashback_used=rep.cashback_used,
        cashback_earned=rep.cashback_earned,
        gross_sale=rep.gross_sale,
        total_orders=rep.total_orders,
        average_order=rep.average_order,
        days=[
            DayPointOut(
                date=d.date,
                total_revenue=d.total_revenue,
                cash_revenue=d.cash_revenue,
                card_revenue=d.card_revenue,
                deposit_revenue=d.deposit_revenue,
                cashback_used=d.cashback_used, cashback_earned=d.cashback_earned,
                gross_sale=d.gross_sale, count=d.count,
            )
            for d in rep.days
        ],
        cogs=rep.cogs,
        gross_profit=rep.gross_profit,
        expenses_total=rep.expenses_total,
        net_profit=rep.net_profit,
        expenses_by_category=[
            ExpenseCategoryPointOut(category_id=p.category_id, name=p.name, total=p.total)
            for p in rep.expenses_by_category
        ],
    )


@router.get("/yearly", response_model=YearlyOut)
async def yearly_report(
    _=Depends(admin_required),
    year: Optional[int] = Query(default=None, ge=2000, le=2100),
    analytics: AnalyticsService = Depends(get_analytics_service),
) -> YearlyOut:
    if year is None:
        year, _ = _default_year_month()
    rep = await analytics.yearly_report(year=year)
    return YearlyOut(
        year=rep.year,
        total_revenue=rep.total_revenue,
        cash_revenue=rep.cash_revenue,
        card_revenue=rep.card_revenue,
        deposit_revenue=rep.deposit_revenue,
        cashback_used=rep.cashback_used,
        cashback_earned=rep.cashback_earned,
        gross_sale=rep.gross_sale,
        total_orders=rep.total_orders,
        average_order=rep.average_order,
        months=[
            MonthPointOut(
                month=p.month,
                total_revenue=p.total_revenue,
                cash_revenue=p.cash_revenue,
                card_revenue=p.card_revenue,
                deposit_revenue=p.deposit_revenue,
                cashback_used=p.cashback_used, cashback_earned=p.cashback_earned,
                gross_sale=p.gross_sale, count=p.count,
            )
            for p in rep.months
        ],
        cogs=rep.cogs,
        gross_profit=rep.gross_profit,
        expenses_total=rep.expenses_total,
        net_profit=rep.net_profit,
        expenses_by_category=[
            ExpenseCategoryPointOut(category_id=p.category_id, name=p.name, total=p.total)
            for p in rep.expenses_by_category
        ],
    )


# ============================ Activity ============================

activity_router = APIRouter(prefix="/api/admin/activity", tags=["admin:activity"])


class SignupPointOut(BaseModel):
    date: str
    count: int


class HourPointOut(BaseModel):
    hour: int
    count: int


class WeekdayPointOut(BaseModel):
    weekday: int
    count: int


class ActivityOut(BaseModel):
    since: str
    until: str
    customers_total: int
    signups_by_day: List[SignupPointOut]
    peak_hours: List[HourPointOut]
    peak_weekday: List[WeekdayPointOut]
    peak_hour: Optional[int] = None
    peak_weekday_index: Optional[int] = None


@activity_router.get("", response_model=ActivityOut)
async def activity_report(
    _=Depends(admin_required),
    days: int = Query(default=30, ge=7, le=365),
    analytics: AnalyticsService = Depends(get_analytics_service),
) -> ActivityOut:
    rep = await analytics.activity_report(days=days)
    return ActivityOut(
        since=rep.since, until=rep.until,
        customers_total=rep.customers_total,
        signups_by_day=[SignupPointOut(date=d, count=c) for (d, c) in rep.signups_by_day],
        peak_hours=[HourPointOut(hour=h.hour, count=h.count) for h in rep.peak_hours],
        peak_weekday=[WeekdayPointOut(weekday=w.weekday, count=w.count) for w in rep.peak_weekday],
        peak_hour=rep.peak_hour,
        peak_weekday_index=rep.peak_weekday_index,
    )
