"""Admin dashboard statistikasi — bitta endpoint, hamma grafiklar uchun."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from Data.unit_of_work import UnitOfWork
from Domain.enums import OrderStatus
from webapp.admin.auth import admin_required
from webapp.deps import _container

router = APIRouter(prefix="/api/admin/stats", tags=["admin:stats"])


# ---------------------- Schemas ----------------------

class TodaySummary(BaseModel):
    orders_count: int         # bugun YARATILGAN buyurtmalar (har qanday holat)
    total_revenue: float = 0.0  # bugun yetkazilganlardan jami tushum
    cash_revenue: float     # shundan naqd (kuryer orqali)
    card_revenue: float = 0.0   # shundan karta
    deposit_revenue: float = 0.0  # shundan avans balansidan
    cashback_used: float    # keshbek bilan to'langan qism
    cashback_earned: float  # yangi yaratilgan liability
    gross_sale: float       # items_total — to'liq sotuv summasi
    new_customers: int
    delivered: int


class StatusCount(BaseModel):
    code: str
    label: str
    color_token: str
    count: int


class TopProduct(BaseModel):
    food_id: Optional[int]
    name: str
    quantity_sold: int
    revenue: float


class DayPoint(BaseModel):
    date: str
    revenue: float          # back-compat alias = cash_revenue
    cash_revenue: float = 0.0
    cashback_used: float = 0.0
    count: int


class HourPoint(BaseModel):
    hour: int
    count: int


class DashboardOut(BaseModel):
    today: TodaySummary
    active_orders_by_status: List[StatusCount]
    top_products: List[TopProduct]
    revenue_last_30_days: List[DayPoint]
    orders_by_hour_today: List[HourPoint]
    couriers_total: int
    couriers_active: int
    customers_total: int
    # Cashback dasturining qisqacha holati — dashboard'da KPI sifatida
    cashback_enabled: bool
    cashback_liability_total: float


# ---------------------- Helpers ----------------------

def _now_tashkent_day_start() -> datetime:
    """Toshkent vaqti bo'yicha bugungi 00:00 (UTC formatda).

    Windows'da `zoneinfo` tzdata paketini talab qiladi. Topilmasa, UTC+5 ga fallback.
    """
    from config import get_settings
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(get_settings().timezone)
    except Exception:
        tz = timezone(timedelta(hours=5))
    now_local = datetime.now(tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(timezone.utc)


# ---------------------- Endpoint ----------------------


@router.get("", response_model=DashboardOut)
async def get_dashboard(
    _=Depends(admin_required),
    c=Depends(_container),
) -> DashboardOut:
    sf = c.order_service._sf  # type: ignore[attr-defined]
    now = datetime.now(timezone.utc)
    today_start = _now_tashkent_day_start()
    thirty_days_ago = now - timedelta(days=30)

    async with UnitOfWork(sf) as uow:
        # Bugungi tushum — DELIVERED asos (pul haqiqatda olingan buyurtmalar).
        today_finance = await uow.orders.finance_in_window(today_start, now + timedelta(seconds=1))
        # Bugun YARATILGAN buyurtmalar soni (har qanday holat) — "Bugungi
        # buyurtmalar" KPI'si; tushumdan farqli, yaratish vaqti bo'yicha.
        today_created_count = await uow.orders.count_filtered(since=today_start)
        today_new = await uow.users.count_since(today_start)
        # delivered hisoblash uchun status filter bilan alohida count
        from sqlalchemy import select, func
        res = await uow.session.execute(
            select(func.count(uow.orders.model.id)).where(
                uow.orders.model.delivered_at >= today_start
            )
        )
        today_delivered_count = int(res.scalar_one() or 0)

        # Cashback liability — kompaniya qarzi
        cfg = await uow.settings.get_or_create()
        cashback_liab, _ = await uow.users.cashback_liability_total()

        # Status bo'yicha hozirgi count
        by_status_raw = await uow.orders.count_by_status()
        active_status_counts: list[StatusCount] = []
        for s in OrderStatus:
            if not s.is_active:
                continue
            active_status_counts.append(StatusCount(
                code=s.name,
                label=s.label_uz,
                color_token=s.color_token,
                count=by_status_raw.get(s.name, 0),
            ))

        # Top mahsulotlar (30 kun)
        top_raw = await uow.orders.top_products_since(thirty_days_ago, limit=5)
        top_products = [
            TopProduct(
                food_id=fid, name=name, quantity_sold=qty, revenue=rev,
            )
            for (fid, name, qty, rev) in top_raw
        ]

        # 30 kunlik to'liq finance trendi (DELIVERED asos, mahalliy kun)
        from Service.timeutil import local_tz_name
        day_rows = await uow.orders.finance_by_day_since(
            thirty_days_ago, tz_name=local_tz_name(),
        )
        existing = {row["date"]: row for row in day_rows}
        filled: list[DayPoint] = []
        for i in range(30):
            d = (now - timedelta(days=29 - i)).date().isoformat()
            row = existing.get(d, {})
            total = float(row.get("total_revenue", 0))
            cash = float(row.get("cash_revenue", 0))
            cb = float(row.get("cashback_used", 0))
            cnt = int(row.get("count", 0))
            filled.append(DayPoint(
                date=d, revenue=total, cash_revenue=cash, cashback_used=cb, count=cnt,
            ))
        revenue_trend = filled

        # Bugungi soatlik
        hour_rows = await uow.orders.hourly_counts_for_day(today_start)
        hour_map = {h: c for (h, c) in hour_rows}
        hourly = [HourPoint(hour=h, count=hour_map.get(h, 0)) for h in range(24)]

        # Kuryerlar
        all_couriers = await uow.couriers.list_all_ordered()
        couriers_total = len(all_couriers)
        couriers_active = sum(1 for c in all_couriers if c.is_active)

        # Mijozlar
        customers_total = await uow.users.count_all()

    return DashboardOut(
        today=TodaySummary(
            orders_count=today_created_count,
            total_revenue=today_finance["total_revenue"],
            cash_revenue=today_finance["cash_revenue"],
            card_revenue=today_finance["card_revenue"],
            deposit_revenue=today_finance["deposit_revenue"],
            cashback_used=today_finance["cashback_used"],
            cashback_earned=today_finance["cashback_earned"],
            gross_sale=today_finance["gross_sale"],
            new_customers=today_new,
            delivered=today_delivered_count,
        ),
        active_orders_by_status=active_status_counts,
        top_products=top_products,
        revenue_last_30_days=revenue_trend,
        orders_by_hour_today=hourly,
        couriers_total=couriers_total,
        couriers_active=couriers_active,
        customers_total=customers_total,
        cashback_enabled=bool(cfg.cashback_enabled),
        cashback_liability_total=cashback_liab,
    )
