"""HTTP qatlamining Pydantic skemalari (faqat I/O DTO'lari)."""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from Domain.constants import (
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
    MAX_ADDRESS_DETAILS_LENGTH,
    MAX_ADDRESS_LABEL_LENGTH,
    MAX_BOTTLES_PER_TRANSACTION,
    MAX_ITEMS_PER_ORDER,
    MAX_NOTE_LENGTH,
    MAX_QUANTITY_PER_ITEM,
    MIN_QUANTITY_PER_ITEM,
)


class ProductOut(BaseModel):
    id: int
    name: str
    description: str = ""
    price: Decimal
    # Minimal buyurtma soni — mijoz kamida shuncha dona olishi shart (1 = cheklov yo'q).
    min_quantity: int = 1
    # Har dona necha qaytariladigan idish beradi (0 = sanalmaydi, 1 = oddiy idish).
    bottles_per_unit: int = 1
    image_url: Optional[str] = None

    model_config = ConfigDict(json_schema_extra={"example": {
        "id": 1, "name": "Suv 18.9 l", "description": "", "price": "22000",
        "min_quantity": 2, "bottles_per_unit": 1, "image_url": "/media/foods/abc.jpg",
    }})


class MeOut(BaseModel):
    """Joriy foydalanuvchi haqida ma'lumot — ro'yxatdan o'tgan/o'tmagan + Telegram ma'lumoti."""
    telegram_id: int
    is_registered: bool
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    # Telegram'dan kelgan profil — ro'yxatdan o'tish formasini oldindan to'ldirish uchun.
    tg_first_name: str
    tg_last_name: str = ""
    tg_username: Optional[str] = None
    # Brend nomi — .env dan keladi; UI'da salomlashish va sarlavhalarda ishlatiladi.
    brand_name: str = ""
    # Mijozning hisoblari — UI har sahifada balansni ko'rsatish uchun.
    cashback_balance: Decimal = Decimal("0.00")
    bottles_balance: int = 0
    # Oldindan to'lov (avans) balansi — checkout'da "Balansdan" opsiyasi uchun.
    deposit_balance: Decimal = Decimal("0.00")


class RegisterIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone_number: str = Field(min_length=4, max_length=24)


class CartItemIn(BaseModel):
    food_id: int = Field(gt=0)
    quantity: int = Field(ge=MIN_QUANTITY_PER_ITEM, le=MAX_QUANTITY_PER_ITEM)


class OrderCreateIn(BaseModel):
    items: List[CartItemIn] = Field(min_length=1, max_length=MAX_ITEMS_PER_ORDER)
    latitude: float = Field(ge=LAT_MIN, le=LAT_MAX)
    longitude: float = Field(ge=LON_MIN, le=LON_MAX)
    contact_phone: str = Field(min_length=4, max_length=24)
    note: str = Field(min_length=1, max_length=MAX_NOTE_LENGTH)
    # Mijoz tarafdan keladi (UUID); takroriy POST'larni bitta orderga aylantiradi.
    idempotency_key: Optional[str] = Field(default=None, max_length=64)
    # Yangi (ixtiyoriy) maydonlar — yangi mijozlar ushbu xususiyatlardan foydalanmasdan
    # ham buyurtma berishlari mumkin. Defaultlar — eski xulq-atvor.
    address_label: str = Field(default="", max_length=MAX_ADDRESS_LABEL_LENGTH)
    address_details: str = Field(default="", max_length=MAX_ADDRESS_DETAILS_LENGTH)
    cashback_to_use: Decimal = Field(default=Decimal("0.00"), ge=0)
    bottles_returned: int = Field(default=0, ge=0, le=MAX_BOTTLES_PER_TRANSACTION)
    # To'lov usuli: cash (default) | card | deposit. Service qatlamida ham
    # validatsiya bor (deposit — balans yetarliligi tekshiriladi).
    payment_method: str = Field(default="cash", pattern="^(cash|card|deposit)$")

    @field_validator("note")
    @classmethod
    def _strip_note(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("note_empty")
        return v


class OrderItemOut(BaseModel):
    # food_id Optional — mahsulot admin tomonidan o'chirilgan bo'lsa NULL,
    # lekin food_name/unit_price/quantity snapshot saqlanadi (buyurtma tarixi yo'qolmaydi).
    food_id: Optional[int] = None
    food_name: str
    unit_price: Decimal
    # quantity — AMALDAGI (yetkazilgan) dona. Kuryer yetkazishda o'zgartirmagan
    # bo'lsa buyurtilganga teng. ordered_quantity — mijoz boshida buyurtma qilgan
    # dona (kuryer o'zgartirgan bo'lsa farq qiladi).
    quantity: int
    ordered_quantity: Optional[int] = None


class OrderOut(BaseModel):
    id: int
    # Kunlik raqam (har kuni 1 dan) — NULL bo'lsa eski buyurtma.
    daily_number: Optional[int] = None
    # Ko'rsatish uchun tayyor string: "YYYYMMDD-NN" yoki eski "#id" (fallback).
    # Frontend shuni to'g'ridan-to'g'ri ko'rsatadi — formatlash backend'da.
    display_number: str
    status: str
    status_label: str
    total_amount: Decimal
    contact_phone: str
    note: str = ""
    created_at: Optional[str] = None
    items: List[OrderItemOut] = []
    # Yangi: keshbek va idishlar snapshotidagi qiymatlar
    items_total: Decimal = Decimal("0.00")
    cashback_used: Decimal = Decimal("0.00")
    cashback_earned: Decimal = Decimal("0.00")
    bottles_issued: int = 0
    bottles_returned: int = 0
    address_label: str = ""
    address_details: str = ""
    # To'lov usuli — UI'da "💵 Naqd" / "💳 Karta" / "💰 Balansdan" ko'rsatiladi.
    payment_method: str = "cash"
    payment_method_label: str = "Naqd"


class CourierOut(BaseModel):
    full_name: str
    username: Optional[str] = None
    # Telefon raqami — mijoz buyurtma detalida `tel:` link bilan qo'ng'iroq
    # qila olishi uchun. NULL bo'lsa, faqat Telegram username (yoki yo'q).
    phone_number: Optional[str] = None


class OrderDetailOut(OrderOut):
    """Batafsil buyurtma sahifasi uchun — kuryer, lokatsiya, timeline timestamplari."""
    courier: Optional[CourierOut] = None
    latitude: float
    longitude: float
    map_url: str
    accepted_at: Optional[str] = None
    delivering_at: Optional[str] = None
    arrived_at: Optional[str] = None
    delivered_at: Optional[str] = None
    cancelled_at: Optional[str] = None


class ErrorOut(BaseModel):
    error: str
    message: str


# ---------------------- Address Book ----------------------

class AddressIn(BaseModel):
    label: str = Field(min_length=1, max_length=MAX_ADDRESS_LABEL_LENGTH)
    latitude: float = Field(ge=LAT_MIN, le=LAT_MAX)
    longitude: float = Field(ge=LON_MIN, le=LON_MAX)
    details: str = Field(default="", max_length=MAX_ADDRESS_DETAILS_LENGTH)
    is_default: bool = False


class AddressOut(BaseModel):
    id: int
    label: str
    latitude: float
    longitude: float
    details: str = ""
    is_default: bool


# ---------------------- Balance ----------------------

class BalanceOut(BaseModel):
    cashback_balance: Decimal
    bottles_balance: int
    cashback_enabled: bool = True
    cashback_percent: float
    max_cashback_usage_ratio: float
    # Mijoz UI uchun — slider qadami va minimal qoplash birligi (1000 so'm).
    cashback_use_unit: int = 1000
    # Oldindan to'lov (avans) balansi — checkout "Balansdan" opsiyasi.
    deposit_balance: Decimal = Decimal("0.00")
