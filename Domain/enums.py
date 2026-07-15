from __future__ import annotations

import enum


class OrderStatus(str, enum.Enum):
    """Buyurtma hayot tsikli:

        NEW ─claim─► ACCEPTED ─yo'lga chiqdim─► DELIVERING ─yetib keldim─►
            ARRIVED ─qabul qildim─► DELIVERED
            │
            └─ cancel (admin) ─► CANCELLED  (har qanday holatdan)

    Etaplar:
      * NEW         — yaratildi, hech qaysi kuryer olmagan
      * ACCEPTED    — kuryer guruhdan claim qildi, DM oldi
      * DELIVERING  — kuryer "Yo'lga chiqdim" bosdi, yo'lda
      * ARRIVED     — kuryer yetib keldi, mijozni kutmoqda
                      (mijozga "buyurtmangiz yetib keldi!" alohida bildirishnoma yuboriladi)
      * DELIVERED   — kuryer "Qabul qildim" tasdiqladi: pul + idishlar + yetkaziildi
                      (bildirishnoma o'chiriladi, kuryer yangi buyurtma olishi mumkin)
      * CANCELLED   — admin bekor qildi
    """

    NEW = "new"
    ACCEPTED = "accepted"
    DELIVERING = "delivering"
    ARRIVED = "arrived"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (OrderStatus.DELIVERED, OrderStatus.CANCELLED)

    @property
    def is_active(self) -> bool:
        """Tugallanmagan — kuryer yangi buyurtma olishi mumkinligi tekshiruvi uchun."""
        return self in (
            OrderStatus.NEW,
            OrderStatus.ACCEPTED,
            OrderStatus.DELIVERING,
            OrderStatus.ARRIVED,
        )

    @property
    def label_uz(self) -> str:
        return {
            OrderStatus.NEW: "Yangi",
            OrderStatus.ACCEPTED: "Qabul qilindi",
            OrderStatus.DELIVERING: "Yetkazilmoqda",
            OrderStatus.ARRIVED: "Yetib keldi",
            OrderStatus.DELIVERED: "Yetkazib berildi",
            OrderStatus.CANCELLED: "Bekor qilindi",
        }[self]

    @property
    def emoji(self) -> str:
        """Status uchun standart emoji — bot va webapp ishlatadi."""
        return {
            OrderStatus.NEW: "🆕",
            OrderStatus.ACCEPTED: "👤",
            OrderStatus.DELIVERING: "🚗",
            OrderStatus.ARRIVED: "📍",
            OrderStatus.DELIVERED: "✅",
            OrderStatus.CANCELLED: "❌",
        }[self]

    @property
    def color_token(self) -> str:
        """CSS rang token — frontend `--status-X` orqali stillash uchun."""
        return self.value


class PaymentMethod(str, enum.Enum):
    """Buyurtma to'lov usuli.

      * CASH    — naqd kuryerga. DELIVERED bo'lganda kuryerning cash_balance'iga
                  CASH_COLLECT yoziladi (kuryer puli keyin adminga topshiriladi).
      * CARD    — karta orqali kompaniyaga. Kuryer pul olmaydi — cash ledger'ga
                  hech narsa yozilmaydi.
      * DEPOSIT — mijozning oldindan to'langan balansi (MChJ avans). Buyurtma
                  yaratilishida balansdan escrow ushlanadi (DEPOSIT_SPEND);
                  bekor bo'lsa qaytariladi. Kuryerdan pul so'ralmaydi.

    DB'da oddiy VARCHAR(16) sifatida `.value` saqlanadi (enum-nom/qiymat
    chalkashligining oldini olish uchun SAEnum ishlatilmaydi).
    """

    CASH = "cash"
    CARD = "card"
    DEPOSIT = "deposit"

    @property
    def label_uz(self) -> str:
        return {
            PaymentMethod.CASH: "Naqd",
            PaymentMethod.CARD: "Karta",
            PaymentMethod.DEPOSIT: "Balansdan",
        }[self]

    @property
    def emoji(self) -> str:
        return {
            PaymentMethod.CASH: "💵",
            PaymentMethod.CARD: "💳",
            PaymentMethod.DEPOSIT: "💰",
        }[self]

    @classmethod
    def parse(cls, raw: str | None) -> "PaymentMethod":
        """API'dan kelgan qiymatni xavfsiz o'girish — noma'lum → CASH emas,
        xato: to'lov usuli pul semantikasi, jimgina default xavfli."""
        value = (raw or "").strip().lower()
        if not value:
            return cls.CASH
        return cls(value)  # ValueError — service qatlamida ValidationError'ga o'giriladi
