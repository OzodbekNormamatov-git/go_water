"""Avto-eslatma jurnali — har yuborilgan "suv kerakmi?" eslatmasi.

Maqsad:
  * Dedup / cooldown — bitta siklda ikki marta yubormaslik
  * Churn cap — oxirgi buyurtmadan keyin nechta eslatma yuborilganini sanash
  * Konversiya tahlili — eslatmadan keyin mijoz buyurtma berdimi (`reordered_at`)

Append-only mantiq (ledger falsafasi kabi) — yozuvlar o'chirilmaydi.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
)
from sqlalchemy.orm import Mapped, mapped_column

from Domain.models.base import Base, _utcnow


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (
        Index("ix_reminders_customer", "customer_id", "sent_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True,
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False,
    )
    # Hisoblangan tugash sanasi (mahalliy) — qaysi kun uchun eslatma.
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Shu eslatmada ishlatilgan sikl (kun) — tahlil/debug uchun.
    cycle_days: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    # Eslatma asoslangan oxirgi DELIVERED buyurtma (audit).
    anchor_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True,
    )
    # Eslatmadan keyin mijoz buyurtma bergan vaqt (konversiya). NULL = hali yo'q.
    reordered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
