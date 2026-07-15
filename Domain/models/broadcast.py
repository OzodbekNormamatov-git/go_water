"""Ommaviy xabarnomalar (Rassilka) — admin barcha mijozlarga xabar yuboradi.

Service qatlami `BroadcastService` asinxron yuborish jarayonini boshqaradi
va davriy ravishda statusni yangilab boradi: PENDING → SENDING → DONE/FAILED.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum as SAEnum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from Domain.models.base import Base, TimestampMixin


class BroadcastStatus(str, enum.Enum):
    PENDING = "pending"      # Yaratilgan, lekin hali yuborish boshlanmagan
    SENDING = "sending"      # Hozir yuborilmoqda
    DONE = "done"            # Yuborish tugadi (qisman muvaffaqiyat ham)
    FAILED = "failed"        # Boshlana olmadi (masalan, ichki xato)
    CANCELLED = "cancelled"  # Admin to'xtatib qo'ydi

    @property
    def is_terminal(self) -> bool:
        return self in (BroadcastStatus.DONE, BroadcastStatus.FAILED, BroadcastStatus.CANCELLED)


class Broadcast(Base, TimestampMixin):
    """Bitta rassilka — kompleks operatsiya, foreground-task sifatida ishlaydi."""

    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Yaratgan admin'ning Telegram ID si (audit uchun)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)

    title: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Ixtiyoriy rasm — agar mavjud bo'lsa, send_photo(caption=body) bilan birgalikda
    # yuboriladi (bitta xabar). Telegram caption chegarasi: 1024 belgi.
    photo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[BroadcastStatus] = mapped_column(
        SAEnum(BroadcastStatus, name="broadcast_status", native_enum=False, length=16),
        default=BroadcastStatus.PENDING,
        nullable=False,
        index=True,
    )

    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Yuborish davomida tushgan eng oxirgi xatoning qisqa matni (debug uchun).
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
