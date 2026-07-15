"""Append-only moliyaviy jurnal — barcha balans o'zgarishlarining o'zgarmas tarixi.

Pattern: double-entry / event-sourcing soddalashtirilgan ko'rinishi (Stripe,
bank backendlari, ERP — universal). Har bir balans o'zgarishi (keshbek topish/
ishlatish/qaytarish, idish berish/qaytarib olish, kuryer naqd yig'ish/topshirish)
shu jadvalga BITTA o'zgarmas qator sifatida yoziladi.

Asosiy tamoyillar:
  * **Faqat qo'shiladi (append-only)** — qatorlar hech qachon UPDATE/DELETE qilinmaydi.
  * **balance_after** — har yozuvda shu operatsiyadan KEYINGI balans muzlatiladi
    (audit + tezkor o'qish). `balance_after = oldingi_balans + delta` (invariant).
  * **Keshlangan proyeksiya** — `users.cashback_balance/bottles_balance` va
    `couriers.cash_balance` ustunlari shu jurnalning yig'indisi (tezlik uchun
    saqlanadi, lekin haqiqat manbai — jurnal). Buzilsa jurnal'dan qayta tiklanadi.
  * **idempotency_key** — bir xil operatsiya ikki marta yozilmasligi uchun
    (masalan, buyurtma yetkazib berilishi: `order:42:cashback_earn`).

Balanslar har xil tur (keshbek/naqd — pul Decimal, idish — butun son), lekin
bitta jadvalda uniform `delta`/`balance_after` (Numeric) sifatida saqlanadi —
`account` ustuni qaysi balans ekanini bildiradi. Idish qiymatlari butun
(masalan, 3.00) bo'lib o'qiyotganda int ga keltiriladi.
"""
from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from Domain.models.base import Base, _utcnow


class LedgerSubject(str, enum.Enum):
    """Balans egasi — kim/nima uchun yozuv."""
    USER = "user"        # mijoz (cashback, bottles)
    COURIER = "courier"  # kuryer (cash)


class LedgerAccount(str, enum.Enum):
    """Qaysi balans o'zgaryapti."""
    CASHBACK = "cashback"  # mijoz keshbek hisobi (so'm)
    BOTTLES = "bottles"    # mijoz qo'lidagi idishlar (dona)
    CASH = "cash"          # kuryer qo'lidagi naqd (so'm)
    DEPOSIT = "deposit"    # mijoz oldindan to'lov (avans) balansi (so'm)


class LedgerKind(str, enum.Enum):
    """Operatsiya semantik turi (nima uchun balans o'zgardi)."""
    OPENING_BALANCE = "opening_balance"   # ledger joriy etilishida backfill seed

    # Keshbek (mijoz)
    CASHBACK_EARN = "cashback_earn"       # DELIVERED — yangi keshbek qo'shildi (+)
    CASHBACK_SPEND = "cashback_spend"     # buyurtma yaratishda escrow ushlandi (−)
    CASHBACK_REFUND = "cashback_refund"   # buyurtma bekor qilindi — escrow qaytdi (+)
    CASHBACK_ADJUST = "cashback_adjust"   # admin qo'lda tuzatdi (±)

    # Idishlar (mijoz)
    BOTTLE_ISSUE = "bottle_issue"         # DELIVERED — idish berildi (+)
    BOTTLE_RETURN = "bottle_return"       # DELIVERED — bo'sh idish qaytarib olindi (−)
    BOTTLE_ADJUST = "bottle_adjust"       # admin qo'lda tuzatdi (±)

    # Naqd (kuryer)
    CASH_COLLECT = "cash_collect"         # DELIVERED — mijozdan naqd olindi (+)
    CASH_SETTLE = "cash_settle"           # kuryer kompaniyaga topshirdi (−)

    # Depozit / avans (mijoz)
    DEPOSIT_TOPUP = "deposit_topup"       # admin balansni to'ldirdi (+)
    DEPOSIT_SPEND = "deposit_spend"       # buyurtma yaratishda ushlandi (−)
    DEPOSIT_REFUND = "deposit_refund"     # buyurtma bekor/kamaytirildi — qaytdi (+)
    DEPOSIT_ADJUST = "deposit_adjust"     # admin qo'lda tuzatdi (±)


class LedgerEntry(Base):
    """Bitta o'zgarmas balans harakati."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        # Subyektning bitta hisobidagi tarixini tez o'qish uchun.
        Index("ix_ledger_subject", "subject_type", "subject_id", "account", "id"),
        # Buyurtmaga bog'liq yozuvlarni topish uchun.
        Index("ix_ledger_order_id", "order_id"),
        # Idempotency — bir xil operatsiya ikki marta yozilmasin (NULL'lar erkin).
        Index(
            "uq_ledger_idempotency",
            "subject_type", "subject_id", "account", "idempotency_key",
            unique=True,
            postgresql_where="idempotency_key IS NOT NULL",
        ),
    )

    # BigInteger — 10 yillik hajm uchun (2^31 dan oshmasin). Postgres'da BIGSERIAL.
    # SQLite variant — testlarda auto-increment ishlashi uchun (SQLite faqat
    # INTEGER PRIMARY KEY'ni auto-increment qiladi).
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True,
    )

    # Balans egasi (users.id yoki couriers.id — FK EMAS, chunki subject_type
    # bilan birga polimorf; soft-delete'da ham yozuv saqlanishi shart).
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    account: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)

    # O'zgarish miqdori (±) va operatsiyadan keyingi balans. Idish uchun ham
    # Numeric (butun qiymat, masalan 3.00) — o'qiyotganda int ga keltiriladi.
    delta: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    # Bog'liq buyurtma (bo'lsa) — audit va tushuntirish uchun.
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True,
    )
    # Operator/admin Telegram ID (qo'lda tuzatish/operator buyurtmasi uchun).
    operator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Erkin matn izoh (admin sababi yoki tizim tushuntirishi).
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # Takroriy yozuvni bloklash kaliti (masalan "order:42:cashback_earn").
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False,
    )
