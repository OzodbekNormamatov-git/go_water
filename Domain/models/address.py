"""Mijozning saqlangan manzillari — Address Book.

Mijoz har safar qayta yozmasdan, "Uy", "Ishxona" kabi tanlash uchun
manzillarni nomlab saqlaydi. Buyurtma yaratish paytida snapshot
sifatida `Order.delivery_latitude/longitude` ga ko'chiriladi —
keyinchalik manzil tahrir qilinsa-da, eski buyurtmaga ta'sir qilmaydi.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from Domain.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from Domain.models.user import User


class CustomerAddress(Base, TimestampMixin):
    """Bir mijozning bitta saqlangan manzili.

    `label` — foydalanuvchiga ko'rinadigan nom (masalan, "Uy", "Ishxona");
    bir mijoz ichida noyob (case-insensitive emas, oddiy unique constraint).
    """

    __tablename__ = "customer_addresses"
    __table_args__ = (
        UniqueConstraint("customer_id", "label", name="uq_customer_addresses_customer_label"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    label: Mapped[str] = mapped_column(String(40), nullable=False)
    details: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    # Mijoz default manzilini belgilashi mumkin — checkout'da oldindan tanlanadi.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    customer: Mapped["User"] = relationship(back_populates="addresses", lazy="selectin")
