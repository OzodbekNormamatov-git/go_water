"""Kompaniya rasxodlari — P&L (foyda-zarar) modulining poydevori.

Uch jadval:
  * `expense_categories` — kengayuvchan kategoriyalar (ijara, oylik, benzin...).
    Jadval (enum EMAS) — admin migratsiyasiz yangi kategoriya qo'shadi.
  * `recurring_expenses` — doimiy rasxod SHABLONI (masalan, "Ofis ijarasi,
    har oyning 1-sanasi, 3 mln"). O'zi hisobotga KIRMAYDI.
  * `expenses` — konkret rasxod yozuvlari. Hisobot faqat shulardan o'qiydi.

Materializatsiya tamoyili (kelishilgan best practice):
  Doimiy rasxod har davr uchun ALOHIDA `expenses` qatori sifatida yaratiladi
  (virtual hisoblanmaydi). Sabab: har oylik ijara alohida tahrirlanadigan,
  auditlanadigan yozuv (bir oy ijara oshdi — faqat o'sha qatorni o'zgartirasiz).
  Idempotentlik: UNIQUE(recurring_id, spent_on) — `daily_order_counters`
  falsafasi, bir davr uchun ikki marta yozilmaydi.

Eslatma: bu jadval `ledger_entries`dan ATAYLAB ajratilgan — ledger mijoz/kuryer
SUBYEKT balansi uchun, bu esa KOMPANIYA xarajati (boshqa domen).
"""
from __future__ import annotations

import enum
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from Domain.models.base import Base, SoftDeleteMixin, TimestampMixin


class ExpensePeriod(str, enum.Enum):
    """Doimiy rasxod davri."""
    MONTHLY = "monthly"  # anchor_day = oyning sanasi (1..31, oy oxiriga clamp)
    WEEKLY = "weekly"    # anchor_day = hafta kuni (0=Dushanba .. 6=Yakshanba)
    YEARLY = "yearly"    # anchor_month (1..12) + anchor_day


class ExpenseCategory(Base, TimestampMixin, SoftDeleteMixin):
    """Rasxod kategoriyasi — admin boshqaradi, soft-delete bilan arxivlanadi."""

    __tablename__ = "expense_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)


class RecurringExpense(Base, TimestampMixin, SoftDeleteMixin):
    """Doimiy rasxod shabloni — davriy `expenses` qatorlarini generatsiya qiladi."""

    __tablename__ = "recurring_expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    # RESTRICT — shablonlar bor kategoriya hard-delete qilinmaydi (soft-delete bor).
    category_id: Mapped[int] = mapped_column(
        ForeignKey("expense_categories.id", ondelete="RESTRICT"), index=True, nullable=False,
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    period: Mapped[ExpensePeriod] = mapped_column(
        SAEnum(ExpensePeriod, name="expense_period", native_enum=False, length=16),
        nullable=False,
        default=ExpensePeriod.MONTHLY,
    )
    # MONTHLY/YEARLY: oy sanasi (1..31, qisqa oyda oxirgi kunga clamp).
    # WEEKLY: hafta kuni (0=Dushanba .. 6=Yakshanba).
    anchor_day: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    # Faqat YEARLY uchun: qaysi oy (1..12). Boshqa davrlarda NULL.
    anchor_month: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # Shu sanadan boshlab davrlar generatsiya qilinadi (shu sana ham kiradi).
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    # NULL = muddatsiz. Berilsa — shu sanagacha (shu sana ham kiradi).
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    category: Mapped["ExpenseCategory"] = relationship(lazy="selectin")


class Expense(Base, TimestampMixin, SoftDeleteMixin):
    """Bitta konkret rasxod yozuvi — hisobot faqat shulardan o'qiydi."""

    __tablename__ = "expenses"
    __table_args__ = (
        # Materializatsiya idempotentligi: bitta shablon bitta sanaga bitta yozuv.
        Index(
            "uq_expenses_recurring_period",
            "recurring_id", "spent_on",
            unique=True,
            postgresql_where=text("recurring_id IS NOT NULL"),
        ),
        # Davr bo'yicha hisobot filtri uchun.
        Index("ix_expenses_spent_on_desc", "spent_on"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("expense_categories.id", ondelete="RESTRICT"), index=True, nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Rasxod qaysi sanaga tegishli (mahalliy sana) — hisobot davri shu bo'yicha.
    spent_on: Mapped[date] = mapped_column(Date, nullable=False)
    # QAMROV DAVRI (ixtiyoriy) — oldindan to'langan rasxodlar uchun.
    # Masalan: oylik 6 oyga oldindan to'landi → period_start=to'lov oyi boshi,
    # period_end=6 oy keyin. Hisobot summani davr kunlariga PROPORTSIONAL
    # taqsimlaydi: har oyga faqat o'sha oyga to'g'ri kelgan ulush kiradi
    # ("faqat ishlatilgan rasxod hisoblanadi" qoidasi).
    # NULL = oddiy rasxod — to'liq summa spent_on sanasiga tushadi.
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Kim kiritdi (admin Telegram ID) — audit. NULL = tizim (materializatsiya).
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Shablondan yaratilgan bo'lsa — manba. RESTRICT: shablon soft-delete bilan
    # arxivlanadi, hard-delete esa materializatsiya tarixini buzmasin.
    recurring_id: Mapped[int | None] = mapped_column(
        ForeignKey("recurring_expenses.id", ondelete="RESTRICT"), nullable=True,
    )

    category: Mapped["ExpenseCategory"] = relationship(lazy="selectin")
