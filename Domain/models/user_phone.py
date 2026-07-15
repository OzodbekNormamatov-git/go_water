"""Mijoz telefon raqamlari — bir mijozga cheklanmagan sonda raqam (one-to-many).

Nega alohida jadval:
  * Mijozlar har xil raqamdan qo'ng'iroq qiladi/buyurtma beradi — operator
    yangi raqamni MAVJUD mijozga biriktiradi, dublikat profil yaratilmaydi.
  * `users.phone_number` ORQADA QOLADI — u "asosiy (primary) telefon KESHI"
    (balans ustunlari ledger'ning keshi bo'lgani kabi). Haqiqat manbai — shu
    jadval. Primary o'zgarsa kesh ham sinxron yangilanadi (UserService).

Identifikatsiya kaliti: `phone` GLOBAL UNIQUE — bitta raqam ko'pi bilan
BITTA mijozga tegishli bo'lishi mumkin. Bu identity-merge oqimining asosi.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from Domain.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from Domain.models.user import User


class UserPhone(Base, TimestampMixin):
    """Bitta mijozning bitta telefon raqami (E.164, masalan +998901234567)."""

    __tablename__ = "user_phones"
    __table_args__ = (
        # Har mijozda ko'pi bilan BITTA primary raqam (partial unique).
        Index(
            "uq_user_phones_primary_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    # E.164 normalizatsiyalangan raqam. GLOBAL unique — identifikatsiya kaliti.
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    # Primary — `users.phone_number` keshi bilan sinxron (UserService boshqaradi).
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Ixtiyoriy izoh: "asosiy", "ish", "turmush o'rtog'i" va h.k.
    label: Mapped[str | None] = mapped_column(String(40), nullable=True)

    user: Mapped["User"] = relationship(back_populates="phones")

    def __repr__(self) -> str:  # pragma: no cover
        star = "*" if self.is_primary else ""
        return f"<UserPhone user={self.user_id} {self.phone}{star}>"
