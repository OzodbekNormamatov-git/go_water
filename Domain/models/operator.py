from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from Domain.models.base import Base, SoftDeleteMixin, TimestampMixin


class Operator(Base, TimestampMixin, SoftDeleteMixin):
    """Call-operator — admin botga /start bosib ro'yxatdan o'tadi (kuryer patterni).

    Lifecycle (Courier bilan bir xil):
      1. Notanish user admin botga /start bosadi → `is_active=False` bilan
         ro'yxatga olinadi va "admin aktivlashtirishini kuting" javobi oladi.
      2. Admin Mini App "Operatorlar" bo'limidan (yoki admin bot orqali)
         aktivlashtiradi.
      3. Aktiv operator admin botning operator menyusi + Mini App'dagi
         "Yangi buyurtma" sahifasidan foydalanadi. Admin-only bo'limlarga
         (mahsulot CRUD, kuryerlar, moliya) kira olmaydi.

    Jadval — YAGONA haqiqat manbai (.env ro'yxati yo'q). Yangi nomzod /start
    bosganda adminlarga DM xabar boradi (aktivlashtirish eslatmasi).

    Arxivlash YO'Q (egasi talabi): ishdan ketgan operator shunchaki NOAKTIV
    qilinadi va ro'yxatda ko'rinib turadi. `deleted_at` ustuni (SoftDeleteMixin)
    tarixiy sabab bilan jadvalda qoladi, lekin HECH QAYERDA o'qilmaydi —
    filtr sifatida qayta kiritmang. `orders.created_by_operator_id` va
    `operator_calls.operator_id` (raw Telegram ID) audit tarixida qoladi.
    """

    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Aloqa raqami (E.164, +998...). NULL — hali kiritilmagan.
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Yangi operator default'da NOAKTIV — admin aktiv qilib qo'yadi (kuryerlardek).
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Operator admin botga /start bosgan (DM mumkin). Seed orqali kelganlarda
    # False bo'lishi mumkin — /start bosganda True bo'ladi.
    has_started_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Operator id={self.id} tg={self.telegram_id} name={self.full_name!r} active={self.is_active}>"
