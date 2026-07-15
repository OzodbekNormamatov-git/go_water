"""Admin sozlamalari — cashback boshqaruv.

Endpoints:
  GET   /api/admin/settings           — joriy konfiguratsiya
  PATCH /api/admin/settings           — sozlamalarni yangilash
  GET   /api/admin/settings/cashback  — cashback dasturining moliyaviy ko'rinishi
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from Service.analytics_service import AnalyticsService
from Service.exceptions import DomainError, ValidationError
from Service.settings_service import SettingsService
from webapp.admin.auth import admin_required
from webapp.deps import get_analytics_service, get_settings_service

router = APIRouter(prefix="/api/admin/settings", tags=["admin:settings"])


# ---------------------- Schemas ----------------------

class CashbackSettingsOut(BaseModel):
    cashback_enabled: bool
    cashback_percent: Decimal
    max_cashback_usage_ratio: Decimal


class CashbackSettingsIn(BaseModel):
    cashback_enabled: Optional[bool] = None
    # 0..50% chegarasi service'da validatsiya qilinadi.
    cashback_percent: Optional[Decimal] = Field(default=None, ge=0, le=50)
    # 0..1 (0..100%); 1.0 = to'liq qoplash mumkin
    max_cashback_usage_ratio: Optional[Decimal] = Field(default=None, ge=0, le=1)


class RemindersSettingsOut(BaseModel):
    reminders_enabled: bool
    reminder_lead_days: int


class RemindersSettingsIn(BaseModel):
    reminders_enabled: Optional[bool] = None
    # Sikl tugashidan necha kun OLDIN (0 = aynan kuni). Faqat kunlarda.
    reminder_lead_days: Optional[int] = Field(default=None, ge=0, le=30)


class CashbackOverviewOut(BaseModel):
    """Cashback dasturining moliyaviy ko'rinishi."""
    config_enabled: bool
    config_percent: float
    config_max_usage_ratio: float
    liability_total: float
    customers_with_balance: int
    cashback_used_all_time: float
    cashback_earned_all_time: float
    bottles_outstanding_total: int
    customers_with_bottles: int


# ---------------------- Endpoints ----------------------

@router.get("", response_model=CashbackSettingsOut)
async def get_settings(
    _=Depends(admin_required),
    settings: SettingsService = Depends(get_settings_service),
) -> CashbackSettingsOut:
    cfg = await settings.get_cashback_config()
    return CashbackSettingsOut(
        cashback_enabled=cfg.enabled,
        cashback_percent=cfg.percent,
        max_cashback_usage_ratio=cfg.max_usage_ratio,
    )


@router.patch("", response_model=CashbackSettingsOut)
async def update_settings(
    payload: CashbackSettingsIn,
    _=Depends(admin_required),
    settings: SettingsService = Depends(get_settings_service),
) -> CashbackSettingsOut:
    try:
        cfg = await settings.update_cashback(
            enabled=payload.cashback_enabled,
            percent=payload.cashback_percent,
            max_usage_ratio=payload.max_cashback_usage_ratio,
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DomainError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return CashbackSettingsOut(
        cashback_enabled=cfg.enabled,
        cashback_percent=cfg.percent,
        max_cashback_usage_ratio=cfg.max_usage_ratio,
    )


@router.get("/reminders", response_model=RemindersSettingsOut)
async def get_reminders(
    _=Depends(admin_required),
    settings: SettingsService = Depends(get_settings_service),
) -> RemindersSettingsOut:
    cfg = await settings.get_reminders_config()
    return RemindersSettingsOut(
        reminders_enabled=cfg.enabled, reminder_lead_days=cfg.lead_days,
    )


@router.patch("/reminders", response_model=RemindersSettingsOut)
async def update_reminders(
    payload: RemindersSettingsIn,
    _=Depends(admin_required),
    settings: SettingsService = Depends(get_settings_service),
) -> RemindersSettingsOut:
    try:
        cfg = await settings.update_reminders(
            enabled=payload.reminders_enabled,
            lead_days=payload.reminder_lead_days,
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DomainError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RemindersSettingsOut(
        reminders_enabled=cfg.enabled, reminder_lead_days=cfg.lead_days,
    )


@router.get("/cashback", response_model=CashbackOverviewOut)
async def cashback_overview(
    _=Depends(admin_required),
    analytics: AnalyticsService = Depends(get_analytics_service),
) -> CashbackOverviewOut:
    """Cashback dasturining yakuniy moliyaviy ko'rinishi (rahbar uchun)."""
    rep = await analytics.cashback_overview()
    return CashbackOverviewOut(
        config_enabled=rep.config_enabled,
        config_percent=rep.config_percent,
        config_max_usage_ratio=rep.config_max_usage_ratio,
        liability_total=rep.liability_total,
        customers_with_balance=rep.customers_with_balance,
        cashback_used_all_time=rep.cashback_used_all_time,
        cashback_earned_all_time=rep.cashback_earned_all_time,
        bottles_outstanding_total=rep.bottles_outstanding_total,
        customers_with_bottles=rep.customers_with_bottles,
    )
