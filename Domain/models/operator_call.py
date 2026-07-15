"""Operator qo'ng'iroqlari jurnali — Aqlli eslatma (mijoz qayta buyurtma) uchun.

Maqsad:
  * Ikki operator bir mijozga qayta-qayta qo'ng'iroq qilmasin (oxirgi qo'ng'iroq
    natijasi Aqlli eslatma ro'yxatida ko'rinadi).
  * "Keyinroq chaqiring" (snooze) — mijoz ro'yxatdan vaqtincha yashiriladi.
  * Konversiya tahlili — qo'ng'iroqdan keyin buyurtma bo'ldimi (reminders
    jadvalidagi `reordered_at` falsafasi bilan hamohang).

Append-only mantiq (ledger falsafasi) — yozuvlar o'chirilmaydi/o'zgartirilmaydi.
"""
from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from Domain.models.base import Base, _utcnow


class CallOutcome(str, enum.Enum):
    """Qo'ng'iroq natijasi."""
    ORDERED = "ordered"        # mijoz buyurtma berdi (operator kiritdi)
    NO_ANSWER = "no_answer"    # javob bermadi
    REFUSED = "refused"        # hozircha kerak emas dedi
    SNOOZED = "snoozed"        # keyinroq chaqirishni so'radi (snooze_until bilan)

    @property
    def label_uz(self) -> str:
        return {
            CallOutcome.ORDERED: "Buyurtma berdi",
            CallOutcome.NO_ANSWER: "Javob bermadi",
            CallOutcome.REFUSED: "Kerak emas dedi",
            CallOutcome.SNOOZED: "Keyinroq chaqirish",
        }[self]


class OperatorCall(Base):
    """Bitta operator qo'ng'irog'i qaydi."""

    __tablename__ = "operator_calls"
    __table_args__ = (
        # Mijozning oxirgi qo'ng'irog'ini tez topish uchun.
        Index("ix_operator_calls_customer_called", "customer_id", "called_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True,
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    # Qo'ng'iroq qilgan operator/admin Telegram ID (audit).
    operator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    called_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False,
    )
    outcome: Mapped[CallOutcome] = mapped_column(
        SAEnum(CallOutcome, name="call_outcome", native_enum=False, length=16),
        nullable=False,
    )
    # Shu sanagacha mijoz Aqlli eslatma ro'yxatida ko'rinmaydi (mahalliy sana).
    snooze_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(String(255), nullable=False, default="")
