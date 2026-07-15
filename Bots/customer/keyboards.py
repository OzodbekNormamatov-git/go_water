from __future__ import annotations

from typing import Optional, Sequence

from aiogram.types import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from Domain.models.food import Food


# ---------------------- Tugmalar matnlari (markerlar) ----------------------
# Markerlar — bot.py da F.text == ... orqali tutiladi.

BTN_PRODUCTS = "💧 Mahsulotlar"
BTN_CART = "🛒 Savatcha"
BTN_MY_ORDERS = "📦 Mening buyurtmalarim"

BTN_BACK = "⬅️ Orqaga"
BTN_CHECKOUT = "📃 Buyurtmani rasmiylashtirish"
BTN_CLEAR_CART = "🗑 Savatchani tozalash"

BTN_OPEN_WEBAPP = "🌐 Tezkor buyurtma (Web App)"

BTN_CONFIRM = "✅ Tasdiqlash"
BTN_CANCEL = "❌ Bekor qilish"

BTN_SEND_PHONE = "📱 Raqamni yuborish"
BTN_SEND_LOCATION = "📍 Lokatsiyamni yuborish"


# ---------------------- Asosiy menyu ----------------------

def main_menu_kb(webapp_url: Optional[str] = None) -> ReplyKeyboardMarkup:
    """Mijoz asosiy menyusi.

    Eslatma: Mini App'ni ochish uchun chat input chap pastdagi **Menu Button**
    ishlatiladi (`main.py:setChatMenuButton`). Reply-keyboard'da takroriy
    "Web App" tugmasi qo'yilmaydi — bir xil funksiya 2 ta joyda noqulay.
    `webapp_url` parametri call-site'larni buzmaslik uchun saqlangan.
    """
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text=BTN_PRODUCTS)],
        [KeyboardButton(text=BTN_CART), KeyboardButton(text=BTN_MY_ORDERS)],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


# ---------------------- Mahsulotlar menyusi ----------------------

def products_menu_kb(foods: Sequence[Food]) -> ReplyKeyboardMarkup:
    """Mahsulotlar reply-keyboardi: 2 ustunli grid + Orqaga + Savatcha.

    Mahsulot tugmasi matni — Food.name (bot.py da nom orqali topiladi).
    """
    rows: list[list[KeyboardButton]] = []
    buttons = [KeyboardButton(text=f.name) for f in foods]
    for i in range(0, len(buttons), 2):
        rows.append(buttons[i : i + 2])

    # "Orqaga" ni oxirgi qatorga juftlik bo'lib qo'shamiz, agar joy bo'lsa.
    back_btn = KeyboardButton(text=BTN_BACK)
    if rows and len(rows[-1]) == 1:
        rows[-1].append(back_btn)
    else:
        rows.append([back_btn])

    rows.append([KeyboardButton(text=BTN_CART)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


# ---------------------- Mahsulot ichidagi miqdor menyusi ----------------------

def quantity_kb(min_quantity: int = 1) -> ReplyKeyboardMarkup:
    """Mahsulot kartasi ochilganda chiqadigan miqdor tugmalari + Orqaga.

    Per-mahsulot minimal buyurtma hisobga olinadi:
      * min <= 3  — eski 3..11 diapazon saqlanadi (UX o'zgarmaydi)
      * min > 3   — tugmalar min..min+8 dan boshlanadi (mijoz noto'g'ri
        sonni tanlay olmaydi; matn kiritsa ham bot validatsiya qiladi)
    """
    min_q = max(1, int(min_quantity or 1))
    start = 3 if min_q <= 3 else min_q
    nums = [start + i for i in range(9)]
    rows = [
        [KeyboardButton(text=str(n)) for n in nums[i:i + 3]]
        for i in range(0, 9, 3)
    ]
    rows.append([KeyboardButton(text=BTN_BACK)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


# ---------------------- Savatcha menyusi ----------------------

def cart_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CHECKOUT)],
            [KeyboardButton(text=BTN_CLEAR_CART), KeyboardButton(text=BTN_BACK)],
        ],
        resize_keyboard=True,
    )


# ---------------------- Tasdiqlash menyusi ----------------------

def confirm_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CONFIRM)],
            [KeyboardButton(text=BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )


# ---------------------- Telefon / Lokatsiya so'rash ----------------------

def request_phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_SEND_PHONE, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def request_location_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_SEND_LOCATION, request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def remove_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
