from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, List

from sqlalchemy import BigInteger, Boolean, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from Domain.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from Domain.models.order import Order


class Courier(Base, TimestampMixin, SoftDeleteMixin):
    """Kuryer — guruhdan zakaz qabul qiladi.

    Soft delete: ishdan ketgan kuryer arxivlanadi. Eski buyurtmalarda ko'rinishi
    saqlanadi (admin tarixini tekshirishi mumkin). `is_active=False` esa vaqtinchalik.
    """

    __tablename__ = "couriers"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Kuryer telefon raqami — mijoz va admin ko'radi (qo'ng'iroq qilish uchun).
    # NULL: hali kiritilmagan (eski kuryerlar yoki /start contact share qilmagan).
    # Format: E.164 (+998901234567). Mijozda tel: link bilan ishlatiladi.
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Yangi kuryer default'da NOAKTIV — admin "Kuryerlar" menyusidan aktiv qilib qo'yadi.
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Telegram cheklovi: bot DM yubora olishi uchun foydalanuvchi avval botga /start yuborgan bo'lishi shart.
    has_started_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Kuryer qo'lidagi NAQD pul — buyurtma DELIVERED bo'lganda mijozdan olingan
    # `total_amount` shu balansga qo'shiladi. Kuryer pulni kompaniyaga topshirganda
    # admin "qabul qildim" (settle) bilan kamaytiradi. Admin har kuryerda qancha
    # naqd borligini ko'rib turadi (qancha pul "yo'lda" ekanini biladi).
    # DB CHECK >= 0 — manfiy bo'la olmaydi (settle balansdan oshmaydi).
    cash_balance: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00"),
    )

    # lazy="noload" — hech kim courier.orders'ni atribut sifatida o'qimaydi
    # (repository so'rovlari ishlatiladi); selectin har kuryer yuklanishida
    # butun buyurtma tarixini sudrab kelardi (User.orders izohiga qarang).
    orders: Mapped[List["Order"]] = relationship(back_populates="courier", lazy="noload")
