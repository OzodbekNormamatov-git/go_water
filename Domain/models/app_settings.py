"""Tizim sozlamalari — bitta singleton qator (id=1).

Hozircha faqat keshbek konfiguratsiyasi shu yerda; kelajakda yangi
sozlamalar shu jadvalga ustun sifatida qo'shiladi (typed schema, ham
DB-level validatsiya, ham IDE autocomplete'ga foyda).

Keshbek o'chirilganda:
  * Yangi buyurtmalar `cashback_earned = 0` (yangi liability yo'q)
  * Mijoz `cashback_to_use > 0` yuborsa — `ValidationError("cashback_disabled")`
  * Eski mijozlarning balansi qoladi (qonuniy huquq), admin manual ajustment
    orqali boshqarish mumkin
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from Domain.constants import DEFAULT_CHURN_AFTER_DAYS, DEFAULT_REMINDER_LEAD_DAYS
from Domain.models.base import Base, TimestampMixin


class AppSettings(Base, TimestampMixin):
    """Singleton sozlamalar qatori. Faqat id=1 mavjud bo'ladi."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True)

    # ---- Cashback config ----
    # Admin ushbu tugma orqali butun cashback dasturini o'chirib/yoqishi mumkin.
    cashback_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    # Har sotuvdan necha % keshbek qaytariladi. NUMERIC(5,2) — 0..999.99% gacha.
    cashback_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("1.5"),
    )
    # Bitta buyurtmada keshbek bilan qoplash maksimal ulushi (0.00..1.00).
    # 1.00 = to'liq qoplash mumkin (mijoz balansi item summasidan katta bo'lsa).
    max_cashback_usage_ratio: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("1.00"),
    )

    # ---- Avto-eslatma config ----
    # Butun "suv kerakmi?" eslatma dasturini yoqish/o'chirish.
    reminders_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    # Sikl tugashidan necha kun OLDIN eslatma yuboriladi (0 = aynan tugash kuni).
    # Admin Mini App'da KUNLARDA sozlanadi (soatlarda emas).
    reminder_lead_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_REMINDER_LEAD_DAYS,
    )

    # ---- Aqlli eslatma config ----
    # Sikl tugagandan keyin necha kun o'tsa mijoz OVERDUE'dan CHURNED'ga o'tadi
    # (operator "yo'qotilgan mijozlar" ro'yxati). Aqlli eslatma segmentatsiyasi.
    reorder_churn_after_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_CHURN_AFTER_DAYS,
    )
