"""Cart item — Mini App (webapp) server-side savatchasi.

DB'da saqlanadi → mijoz Mini App'ni qayta ochsa savatcha yo'qolmaydi.
Buyurtma yaratilgach, cart tozalanadi. Eslatma: mijoz BOTI o'z FSM
(in-memory) savatchasini yuritadi — bu jadval bilan sinxronlanmaydi.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from Domain.models.base import Base, _utcnow

if TYPE_CHECKING:
    from Domain.models.food import Food
    from Domain.models.user import User


class CartItem(Base):
    """Foydalanuvchining hozirgi savatchadagi bitta mahsuloti.

    `(customer_id, food_id)` juftligi yagona — bir xil mahsulot ikki marta
    qo'shilmaydi (qiymat oshiriladi).
    """

    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("customer_id", "food_id", name="uq_cart_items_customer_food"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    food_id: Mapped[int] = mapped_column(
        ForeignKey("foods.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False,
    )

    customer: Mapped["User"] = relationship(lazy="selectin")
    food: Mapped["Food"] = relationship(lazy="selectin")
