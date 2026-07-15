"""Kunlik buyurtma raqami uchun atomik counter — har kun bitta qator.

Order.daily_number shu jadval orqali beriladi. Pattern (POS / e-commerce
standarti — Shopify, Magento, Dynamics 365, fiskal printerlar):
  * `order.id` — global, ++, hech qachon reset bo'lmaydi (PK, idempotency, FK)
  * `order.daily_number` — har kuni 1 dan boshlanadigan, odamlar ko'radigan raqam

Atomik increment:
    INSERT INTO daily_order_counters (day, last_number) VALUES (:day, 1)
    ON CONFLICT (day) DO UPDATE SET last_number = daily_order_counters.last_number + 1
    RETURNING last_number;

Bu bitta statement race-safe (PostgreSQL row lock). Yangi kun → yangi qator
avtomatik (reset logikasi kerak emas). Eski kunlar qatorlari qoladi (jadval
kichik — har kun bitta qator).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Integer
from sqlalchemy.orm import Mapped, mapped_column

from Domain.models.base import Base


class DailyOrderCounter(Base):
    """Bitta kun uchun oxirgi berilgan buyurtma raqami.

    `day` — Toshkent mahalliy sanasi (timezone'siz DATE, faqat kalit sifatida).
    """

    __tablename__ = "daily_order_counters"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
