from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from Domain.models.base import Base, SoftDeleteMixin, TimestampMixin


class Food(Base, TimestampMixin, SoftDeleteMixin):
    """Sotuvdagi mahsulot (ovqat, suv va h.k.). Jadval nomi tarixiy sabablarga ko'ra `foods`.

    Soft delete:
      * `deleted_at IS NULL` — aktiv, mijoz ko'radi va admin Mahsulotlar ro'yxatida.
      * `deleted_at != NULL` — arxivlangan. Mijoz ko'rmaydi, lekin eski buyurtmalarda
        snapshot ko'rinadi. Admin "Arxiv" tab'idan qaytarishi mumkin.
      * `is_available=False` — vaqtinchalik (mahsulot bor lekin sotuvda emas).
        Soft delete'dan farqi: bu doim qaytarish mumkin, admin asosiy ro'yxatda ko'radi.
    """

    __tablename__ = "foods"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Tannarx (COGS) — moliya hisobotida foyda = narx − tannarx. Faqat admin
    # ko'radi/kiritadi. Buyurtma yaratilganda `OrderItem.unit_cost` ga SNAPSHOT
    # qilinadi (xuddi `unit_price` kabi) — keyin o'zgartirilsa tarix buzilmaydi.
    cost_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00"),
    )
    # Minimal buyurtma soni — mijoz shu mahsulotdan kamida shuncha dona olishi shart.
    # Default 1 = cheklov yo'q. Cap: MAX_QUANTITY_PER_ITEM (999). Admin Mini App'da
    # belgilanadi; buyurtma yaratishda server item.quantity >= min_quantity tekshiradi.
    min_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Qaytariladigan idishlar nazorati — har DONA shu mahsulot mijoz idish
    # balansiga necha "qaytariladigan idish" qo'shishini bildiradi:
    #   0 = sanalmaydi (suv pumpasi, kuller, filtr — qaytarib olinmaydi)
    #   1 = oddiy idish (suv baklashkasi)  ← default, eski xulq-atvor saqlanadi
    #   N = bir donada N ta qaytariladigan idish (masalan, 6-li yashik)
    # Buyurtma yaratilganda `OrderItem.bottles_per_unit` ga SNAPSHOT qilinadi —
    # admin keyin bu qiymatni o'zgartirsa, eski buyurtmalarning idish hisobi
    # o'zgarmaydi (xuddi `unit_price`/`food_name` kabi).
    bottles_per_unit: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    image_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
