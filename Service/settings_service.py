"""SettingsService — admin tomonidan boshqariladigan tizim sozlamalari.

Hozircha cashback dasturi konfiguratsiyasi:
  * `cashback_enabled` — butun keshbek tizimini yoqish/o'chirish
  * `cashback_percent` — har sotuvdan necha % qaytariladi
  * `max_cashback_usage_ratio` — bitta buyurtmada keshbek bilan qoplash chegarasi
    (0..1; 1 = to'liq qoplash mumkin)

Validatsiya qoidalari (production guard):
  * percent 0..50 oralig'ida (50% dan oshiq biznes uchun xavfli)
  * ratio 0..1 oralig'ida
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from Data.unit_of_work import UnitOfWork
from Domain.models.app_settings import AppSettings
from Service.exceptions import ValidationError


@dataclass(slots=True)
class CashbackConfig:
    """Sof DTO — caller `AppSettings` ORM obyekti bilan ishlashga majbur emas."""
    enabled: bool
    percent: Decimal
    max_usage_ratio: Decimal


@dataclass(slots=True)
class RemindersConfig:
    """Avto-eslatma sozlamasi (sof DTO)."""
    enabled: bool
    lead_days: int


def _to_config(s: AppSettings) -> CashbackConfig:
    return CashbackConfig(
        enabled=bool(s.cashback_enabled),
        percent=Decimal(s.cashback_percent or 0),
        max_usage_ratio=Decimal(s.max_cashback_usage_ratio or 0),
    )


def _to_reminders(s: AppSettings) -> RemindersConfig:
    return RemindersConfig(
        enabled=bool(s.reminders_enabled),
        lead_days=int(s.reminder_lead_days or 0),
    )


# Validatsiya chegaralari — biznes himoyasi uchun
MIN_PERCENT = Decimal("0.00")
MAX_PERCENT = Decimal("50.00")
MIN_RATIO = Decimal("0.00")
MAX_RATIO = Decimal("1.00")
MAX_REMINDER_LEAD_DAYS = 30


class SettingsService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_cashback_config(self) -> CashbackConfig:
        async with UnitOfWork(self._sf) as uow:
            s = await uow.settings.get_or_create()
            return _to_config(s)

    async def update_cashback(
        self,
        *,
        enabled: Optional[bool] = None,
        percent: Optional[Decimal] = None,
        max_usage_ratio: Optional[Decimal] = None,
    ) -> CashbackConfig:
        """Cashback sozlamalarini atomik yangilaydi.

        Faqat berilgan parametrlar yangilanadi (PATCH semantikasi).
        """
        if percent is not None:
            p = Decimal(str(percent))
            if p < MIN_PERCENT or p > MAX_PERCENT:
                raise ValidationError(
                    "settings_percent_out_of_range",
                    context={"min": float(MIN_PERCENT), "max": float(MAX_PERCENT)},
                )
        if max_usage_ratio is not None:
            r = Decimal(str(max_usage_ratio))
            if r < MIN_RATIO or r > MAX_RATIO:
                raise ValidationError(
                    "settings_ratio_out_of_range",
                    context={"min": float(MIN_RATIO), "max": float(MAX_RATIO)},
                )
        async with UnitOfWork(self._sf) as uow:
            s = await uow.settings.get_for_update()
            if enabled is not None:
                s.cashback_enabled = bool(enabled)
            if percent is not None:
                s.cashback_percent = Decimal(str(percent)).quantize(Decimal("0.01"))
            if max_usage_ratio is not None:
                s.max_cashback_usage_ratio = Decimal(str(max_usage_ratio)).quantize(Decimal("0.01"))
            await uow.settings.add(s)
            return _to_config(s)

    # ---------------------- Avto-eslatma ----------------------

    async def get_reminders_config(self) -> RemindersConfig:
        async with UnitOfWork(self._sf) as uow:
            s = await uow.settings.get_or_create()
            return _to_reminders(s)

    async def update_reminders(
        self, *, enabled: Optional[bool] = None, lead_days: Optional[int] = None,
    ) -> RemindersConfig:
        """Avto-eslatma sozlamasini atomik yangilaydi (PATCH semantikasi).
        `lead_days` — sikl tugashidan necha kun oldin (0..MAX, faqat kunlarda)."""
        if lead_days is not None:
            try:
                ld = int(lead_days)
            except (TypeError, ValueError):
                raise ValidationError(
                    "settings_lead_days_out_of_range",
                    context={"min": 0, "max": MAX_REMINDER_LEAD_DAYS},
                )
            if ld < 0 or ld > MAX_REMINDER_LEAD_DAYS:
                raise ValidationError(
                    "settings_lead_days_out_of_range",
                    context={"min": 0, "max": MAX_REMINDER_LEAD_DAYS},
                )
        async with UnitOfWork(self._sf) as uow:
            s = await uow.settings.get_for_update()
            if enabled is not None:
                s.reminders_enabled = bool(enabled)
            if lead_days is not None:
                s.reminder_lead_days = int(lead_days)
            await uow.settings.add(s)
            return _to_reminders(s)
