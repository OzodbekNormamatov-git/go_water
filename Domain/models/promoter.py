"""Promouterlar — uyma-uy yuruvchi ishchilar va ularning promokodlari.

Biznes oqimi:
  1. Admin promouterni yaratadi va unga NOYOB, O'ZGARMAS promokod beradi.
  2. Promouter mijoznikiga boradi, botni tushuntiradi, manzilini saqlashga
     o'rgatadi (masalan, "Uy").
  3. Mijozning O'Z telefonida, mijoz ruxsati bilan, promouter o'z kodini
     kiritadi → `promoter_redemptions` da bog'lanish paydo bo'ladi.
  4. Keyingi zakazlar shu promouterga yoziladi → KPI/bonus.

Kod NEGA o'zgarmas: kod zakaz qatorlariga snapshot bo'lib muhrlanadi
(`orders.promoter_code`) va bosma materiallarda/vizitkalarda tarqaladi.
O'zgartirilsa, tarix bilan aloqa uziladi. `PromoterService` da update yo'li
umuman ochilmagan — bu ataylab.

ARXIVLASH, hard-delete EMAS (Courier patterni): ishdan ketgan promouter
`deleted_at` bilan arxivlanadi va qatori DB'da ABADIY qoladi. Shuning uchun
`orders.promoter_id` FK'si hech qachon "osilib" qolmaydi va eski zakazlar
buzilmaydi. Tarixiy KPI hisobotlari arxivlangan promouterni ham ko'rsatadi.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from Domain.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from Domain.models.user import User


class Promoter(Base, TimestampMixin, SoftDeleteMixin):
    """Uyma-uy yuruvchi ishchi — bitta noyob promokod egasi.

    Courier/Operator'dan FARQI: promouterda Telegram hisobi/boti YO'Q. U tizimga
    kirmaydi — faqat kodga ega. Shuning uchun `telegram_id`/`has_started_bot`
    ustunlari yo'q. Butun boshqaruv admin panelida.

    `is_active=False` — vaqtinchalik to'xtatish (kod endi o'tmaydi, bonus
    to'planmaydi), `deleted_at` — butunlay ishdan ketgan (arxiv).
    Ikkalasi ham eski zakazlarga TA'SIR QILMAYDI.
    """

    __tablename__ = "promoters"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Aloqa raqami (E.164, +998...). NULL — kiritilmagan.
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # NOYOB va O'ZGARMAS kod. Doim UPPERCASE saqlanadi (`normalize_promo_code`),
    # qidiruv ham normalizatsiyalangan qiymat bo'yicha — mijoz kichik harfda
    # kiritsa ham topiladi.
    promo_code: Mapped[str] = mapped_column(
        String(16), unique=True, index=True, nullable=False,
    )

    # Admin yaratgani uchun default AKTIV (Courier/Operator'da False —
    # ular o'zi /start bosib keladi va admin tasdiqlaydi; bu yerda esa
    # yaratishning o'zi admin harakati).
    is_active: Mapped[bool] = mapped_column(
        default=True, nullable=False, server_default="true",
    )

    redemptions: Mapped[list["PromoterRedemption"]] = relationship(
        back_populates="promoter", lazy="noload",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Promoter id={self.id} code={self.promo_code!r} name={self.full_name!r} active={self.is_active}>"


class PromoterRedemption(Base, TimestampMixin):
    """Mijoz ↔ promouter bog'lanishi — promokod ishlatilgan payt.

    ALOHIDA JADVAL (egasi talabi): `users` jadvaliga ustun qo'shilmaydi.
    Sabab to'g'ri — bu mijozning atributi emas, ikki obyekt orasidagi
    voqea (audit yozuvi): qachon, qaysi kod bilan, qaysi davr uchun.

    `customer_id` UNIQUE — bitta mijoz umrida FAQAT BIR MARTA promokod
    kiritadi. Bu DB darajasidagi kafolat: ikki so'rov bir vaqtda kelsa ham
    (race), ikkinchisi IntegrityError oladi va rad etiladi.

    `created_at` (TimestampMixin) = kod kiritilgan payt.
    """

    __tablename__ = "promoter_redemptions"

    id: Mapped[int] = mapped_column(primary_key=True)

    # CASCADE: mijoz butunlay o'chirilsa (purge/GDPR), bog'lanish ham ketadi.
    # UNIQUE: "bir mijoz — bir marta" qoidasining yakuniy himoyasi.
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True, index=True, nullable=False,
    )
    # RESTRICT: bog'lanishi bor promouterni hard-delete QILIB BO'LMAYDI.
    # Promouterlar baribir soft-delete bilan arxivlanadi — bu qo'shimcha
    # himoya qavati (tarixni tasodifiy yo'q qilishdan saqlaydi).
    promoter_id: Mapped[int] = mapped_column(
        ForeignKey("promoters.id", ondelete="RESTRICT"), index=True, nullable=False,
    )

    # Kod SNAPSHOT'i — promouter qatori biror sabab bilan yo'qolsa ham,
    # bog'lanish qaysi kod orqali bo'lganini o'zi aytib turadi (audit).
    promo_code: Mapped[str] = mapped_column(String(16), nullable=False)

    # Bonus davri tugash sanasi — kod kiritilgan PAYTDAGI
    # `app_settings.promoter_bonus_window_days` dan hisoblanib MUHRLANADI.
    # Nega snapshot: admin ertaga davrni 90 → 30 kunga qisqartirsa, allaqachon
    # bog'langan mijozlarning sharti retroaktiv o'zgarib ketmasin (xuddi
    # `orders.cashback_earned` kabi — kelishuv tuzilgan paytdagi shart amal qiladi).
    bonus_window_ends_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    promoter: Mapped["Promoter"] = relationship(
        back_populates="redemptions", lazy="selectin",
    )
    customer: Mapped["User"] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<PromoterRedemption customer={self.customer_id} "
            f"promoter={self.promoter_id} code={self.promo_code!r}>"
        )
