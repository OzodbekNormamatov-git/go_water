from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List

from sqlalchemy import BigInteger, DateTime, Enum as SAEnum, Float, ForeignKey, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from Domain.enums import OrderStatus
from Domain.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from Domain.models.courier import Courier
    from Domain.models.food import Food
    from Domain.models.user import User


class Order(Base, TimestampMixin, SoftDeleteMixin):
    """Mijozning buyurtmasi.

    Soft delete: admin tomonidan arxivlash (masalan, test buyurtma yoki spam).
    Mijoz "Buyurtmalarim"da ko'rmaydi, stat/finance'ga kirmaydi. CANCELLED status
    bilan farqi: CANCELLED biznes oqimi (mijoz/admin bekor qildi va kuryerga
    yetkazilmadi), DELETED — umuman tizimdan yashirish (audit/cleanup).
    """

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)

    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    courier_id: Mapped[int | None] = mapped_column(
        ForeignKey("couriers.id", ondelete="SET NULL"), nullable=True, index=True
    )

    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, name="order_status", native_enum=False, length=20),
        default=OrderStatus.NEW,
        nullable=False,
        index=True,
    )

    # Mahsulotlar narxining yig'indisi (cashback ishlatishidan oldin).
    items_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    # Buyurtma uchun ishlatilgan keshbek (so'mda).
    cashback_used: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    # Mijoz olishi kerak bo'lgan keshbek (DELIVERED bo'lganda hisobiga qo'shiladi).
    cashback_earned: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    # Yakuniy summa = items_total − cashback_used (mijoz to'laydigan summa).
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    # To'lov usuli — PaymentMethod enum'ining `.value`si ("cash"|"card"|"deposit").
    # Oddiy VARCHAR (SAEnum emas) — enum-nom/qiymat mismatch sinfidan qochish uchun.
    #   * cash    — DELIVERED'da kuryer cash_balance'iga CASH_COLLECT yoziladi
    #   * card    — kuryer pul olmaydi, hech qanday cash yozuvi yo'q
    #   * deposit — yaratilishda mijoz deposit_balance'idan escrow ushlanadi
    payment_method: Mapped[str] = mapped_column(
        String(16), nullable=False, default="cash", server_default="cash",
    )

    # Idishlar nazorati (Bottle balance):
    #   bottles_issued — bu buyurtma orqali mijozga yetkazilayotgan idishlar soni
    #   bottles_returned — mijoz qaytarayotgan bo'sh idishlar soni
    # DELIVERED holatida user.bottles_balance += (issued − returned).
    bottles_issued: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bottles_returned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Yetkazib berish nuqtasi (xaritadan tanlangan yoki Telegram Location)
    delivery_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    delivery_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    # Manzil yorlig'i (masalan, "Uy") va batafsil izoh — addresses jadvalidan
    # snapshot. Manzil kitobi yangilansa, eski buyurtma o'zgarmaydi.
    address_label: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    address_details: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    contact_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Kunlik buyurtma raqami — har kuni (Toshkent vaqti 00:00) 1 dan boshlanadi.
    # `id` (global, ++) DAN FARQLI — bu odamlar ko'radigan qisqa raqam.
    # Yaratilganda atomik counter (daily_order_counters) orqali beriladi.
    # NULL: eski (migration'gacha) buyurtmalar — display'da `#id` ga fallback.
    # `daily_number` o'zi unique EMAS (har kuni qaytadan 1) — sana bilan birga
    # global unique (display: "YYYYMMDD-NN").
    daily_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Idempotency: mijoz UUID/timestamp yuboradi. (customer_id, key) noyob
    # — bir xil kalit bilan qayta yuborish yangi buyurtma yaratmaydi.
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Operator yaratgan buyurtmalar uchun — operator'ning Telegram ID'si.
    # NULL = mijoz o'zi botdan yaratgan. Audit trail va kuryer guruhida
    # "(operator: @username)" ko'rsatish uchun.
    created_by_operator_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True,
    )

    # ---------------------- Promouter atributsiyasi ----------------------
    # Mijozni uyma-uy yurib jalb qilgan ishchi (`promoter_redemptions` orqali).
    # NULL = mijozda promokod bog'lanishi yo'q (oddiy mijoz).
    #
    # ATRIBUTSIYA va BONUS ATAYLAB AJRATILGAN:
    #   * `promoter_id` — "bu mijozni kim olib kelgan" — ABADIY fakt. Promouter
    #     ishdan ketsa yoki bonus davri tugasa HAM yozilaveradi (tahlil buzilmasin).
    #   * `promoter_bonus_amount` — pul. Faqat dastur yoqiq + promouter aktiv +
    #     davr tugamagan bo'lsa > 0 bo'ladi; aks holda 0.
    # Shu sababli "davri tugagan / ishdan ketgan promouter" holati bu jadvalda
    # HECH QANDAY muammo tug'dirmaydi — shunchaki bonusi 0 bo'ladi.
    #
    # SET NULL: promouter qatori majburan hard-delete qilinsa ham zakaz o'chmaydi
    # (amalda bu sodir bo'lmaydi — promouterlar arxivlanadi va
    # `promoter_redemptions.promoter_id` RESTRICT bilan himoyalangan).
    promoter_id: Mapped[int | None] = mapped_column(
        ForeignKey("promoters.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    # Promokod SNAPSHOT'i (`OrderItem.food_name` patterni) — oxirgi himoya:
    # promouter qatori yo'qolsa va `promoter_id` NULL bo'lib qolsa ham, zakaz
    # qaysi kod orqali kelganini o'zi aytib turadi.
    promoter_code: Mapped[str] = mapped_column(
        String(16), nullable=False, default="", server_default="",
    )
    # Shu zakaz uchun promouterga tegishli bonus — YARATILGANDA muhrlanadi
    # (`cashback_earned` patterni). Admin bonusni keyin o'zgartirsa, o'tmishdagi
    # hisobotlar o'zgarmaydi. Faqat DELIVERED bo'lganda haqiqiy hisoblanadi.
    promoter_bonus_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00"), server_default="0",
    )

    # Kuryerlar guruhidagi xabarning telegram message_id si — claim paytida tahrirlanadi
    group_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Biriktirilgan kuryerga shaxsiy DM dagi xabar id si — har transitsiyada tahrirlanadi
    courier_dm_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Mijoz DM dagi yagona "holat lentasi" xabarining id si — har transitsiyada edit qilinadi
    # (5 ta alohida xabar o'rniga bitta o'sib boruvchi timeline).
    customer_dm_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Alohida bildirishnoma xabar — kuryer ARRIVED holatiga o'tganda yuboriladi
    # ("Buyurtmangiz yetib keldi!"). DELIVERED bo'lganda o'chiriladi (e'tiborni jalb qiladi,
    # keyin chiqindi qoldirmaydi). Asosiy timeline xabarga ta'sir qilmaydi.
    customer_arrived_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivering_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    customer: Mapped["User"] = relationship(back_populates="orders", lazy="selectin")
    courier: Mapped["Courier | None"] = relationship(back_populates="orders", lazy="selectin")
    items: Mapped[List["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class OrderItem(Base):
    """Buyurtma tarkibi — mahsulot snapshotidagi narx bilan.

    `food_id` SET NULL bilan, foods.id o'chirilsa ham qator yo'qolmaydi:
    food_name + unit_price + quantity da tarix saqlanadi. Bu admin'ga
    eski mahsulotlarni xavfsiz o'chirish imkonini beradi.
    """

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    food_id: Mapped[int | None] = mapped_column(
        ForeignKey("foods.id", ondelete="SET NULL"), index=True, nullable=True,
    )

    food_name: Mapped[str] = mapped_column(String(120), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Buyurtma vaqtidagi tannarx SNAPSHOT'i (`Food.cost_price` dan) — moliya
    # hisobotida COGS/foyda shu qiymatdan hisoblanadi. Tannarx keyin o'zgarsa,
    # eski buyurtmalarning foydasi o'zgarmaydi (xuddi `unit_price` kabi).
    # Eski (migration'gacha) qatorlarda 0 — foyda hisobida "tannarx noma'lum".
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00"),
    )
    # Mijoz BUYURTMA QILGAN dona (o'zgarmas snapshot — "boshida nechta edi").
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # Kuryer YETKAZGAN haqiqiy dona (eshik oldida mijoz ko'proq/kamroq olishi
    # mumkin). NULL = kuryer o'zgartirmagan (yetkazilgan = buyurtilgan).
    # Barcha pul/idish/foyda hisobi `effective_quantity` (delivered ?? quantity)
    # dan olinadi — kuryer miqdorni o'zgartirsa order noldan qayta hisoblanadi.
    delivered_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Buyurtma vaqtidagi `Food.bottles_per_unit` SNAPSHOT'i — har dona shu
    # mahsulot necha qaytariladigan idish berishini buyurtma yaratilgan paytdagi
    # holatda muzlatadi. Mahsulot keyin "qaytarilmaydi" qilib o'zgartirilsa ham,
    # bu buyurtmaning idish hisobi o'zgarmaydi. Eski (migration'gacha) qatorlarda
    # default 1 — avvalgi "har item = 1 idish" xulq-atvori bilan mos.
    bottles_per_unit: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)

    order: Mapped["Order"] = relationship(back_populates="items")
    food: Mapped["Food | None"] = relationship(lazy="selectin")

    @property
    def effective_quantity(self) -> int:
        """Amaldagi (yetkazilgan) dona — pul/idish/foyda hisobi shundan.
        Kuryer o'zgartirmagan bo'lsa (NULL) — buyurtilgan miqdor."""
        dq = self.delivered_quantity
        return int(dq) if dq is not None else int(self.quantity)

    @property
    def is_quantity_adjusted(self) -> bool:
        """Kuryer yetkazishda miqdorni o'zgartirganmi (display uchun)."""
        return self.delivered_quantity is not None and int(self.delivered_quantity) != int(self.quantity)

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.effective_quantity
