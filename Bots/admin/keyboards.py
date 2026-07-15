from __future__ import annotations

from typing import Optional, Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from Domain.models.courier import Courier
from Domain.models.food import Food


def admin_main_kb(webapp_url: Optional[str] = None) -> ReplyKeyboardMarkup:
    """Admin reply keyboard.

    Web admin paneli endi chat input chap pastdagi **Menu Button** orqali
    ochiladi (main.py'da `setChatMenuButton` o'rnatilgan). Shu sababli
    reply keyboard'da alohida WebApp tugmasi kerak emas — bu yerda faqat
    bot ichki tezkor harakatlar.

    `webapp_url` parametri keyingi versiyalarda foydali bo'lishi mumkin
    (masalan, fallback uchun) — hozir ishlatilmaydi.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_NEW_ORDER)],
            [KeyboardButton(text="💧 Mahsulotlar"), KeyboardButton(text="➕ Yangi mahsulot")],
            [KeyboardButton(text="📦 Buyurtmalar"), KeyboardButton(text="👤 Kuryerlar")],
        ],
        resize_keyboard=True,
    )


def operator_main_kb() -> ReplyKeyboardMarkup:
    """Operator uchun minimal klaviatura — yangi buyurtma + yordam."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_NEW_ORDER)],
            [KeyboardButton(text="ℹ️ Yordam")],
        ],
        resize_keyboard=True,
    )


def foods_list_kb(foods: Sequence[Food]) -> InlineKeyboardMarkup:
    rows = []
    for f in foods:
        prefix = "✅" if f.is_available else "⛔️"
        rows.append([
            InlineKeyboardButton(text=f"{prefix} {f.name} — {f.price}", callback_data=f"adm:food:{f.id}")
        ])
    if not rows:
        rows = [[InlineKeyboardButton(text="Hech narsa yo'q", callback_data="noop")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def food_actions_kb(food: Food) -> InlineKeyboardMarkup:
    toggle_text = "⛔️ O'chirib qo'yish" if food.is_available else "✅ Yoqish"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Nom", callback_data=f"adm:edit:name:{food.id}"),
                InlineKeyboardButton(text="✏️ Tavsif", callback_data=f"adm:edit:desc:{food.id}"),
            ],
            [
                InlineKeyboardButton(text="💰 Narx", callback_data=f"adm:edit:price:{food.id}"),
                InlineKeyboardButton(text="📷 Rasm", callback_data=f"adm:edit:photo:{food.id}"),
            ],
            [InlineKeyboardButton(text=toggle_text, callback_data=f"adm:toggle:{food.id}")],
            [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"adm:delete:{food.id}")],
            [InlineKeyboardButton(text="⬅️ Ro'yxat", callback_data="adm:foods")],
        ]
    )


def confirm_delete_kb(food_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑 Ha, o'chirilsin", callback_data=f"adm:delete_yes:{food_id}"),
                InlineKeyboardButton(text="Bekor", callback_data=f"adm:food:{food_id}"),
            ]
        ]
    )


def skip_photo_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Rasmsiz davom etish", callback_data="adm:new:nophoto")]]
    )


def skip_desc_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Tavsifsiz davom etish", callback_data="adm:new:nodesc")]]
    )


def edit_cancel_kb(food_id: int) -> InlineKeyboardMarkup:
    """Tahrirlash davomida — orqaga qaytib mahsulot kartochkasini ko'rish."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Bekor", callback_data=f"adm:food:{food_id}")]]
    )


# ----------------------------- Kuryerlar -----------------------------

def couriers_list_kb(couriers: Sequence[Courier]) -> InlineKeyboardMarkup:
    rows = []
    for c in couriers:
        mark = "✅" if c.is_active else "⛔️"
        label = f"{mark} {c.full_name}"
        if c.username:
            label += f" (@{c.username})"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"adm:cour:{c.id}")])
    if not rows:
        rows = [[InlineKeyboardButton(text="Hozircha kuryerlar yo'q", callback_data="noop")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def courier_actions_kb(courier: Courier) -> InlineKeyboardMarkup:
    toggle_text = "⛔️ Noaktiv qilish" if courier.is_active else "✅ Aktiv qilish"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data=f"adm:cour_toggle:{courier.id}")],
            [InlineKeyboardButton(text="⬅️ Ro'yxat", callback_data="adm:couriers")],
        ]
    )


# ============================ Operator order (chat FSM) ============================

# Tugma matnlari (markerlar — F.text == ... bilan tutiladi).
BTN_NEW_ORDER = "📞 Yangi buyurtma"
BTN_CANCEL_ORDER = "❌ Bekor qilish"


def request_phone_kb() -> ReplyKeyboardMarkup:
    """Operator mijozning contact'ini share qilish uchun tugma.

    Operator mijozdan qo'ng'iroq qayd qilingan vaqtda Telegram chat'idan
    contact'ni forward qila oladi. Bu yerdagi `request_contact=True` esa
    operatorning O'Z kontaktini yuboradi (ehtiyot bo'lib, biz uni rad etamiz —
    chunki bu mijozning kontakti emas). Yaxshi yondashuv: faqat text input
    yoki forwarded contact xabari.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CANCEL_ORDER)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Mijozning telefon raqami (+998901234567)",
    )


def request_location_kb() -> ReplyKeyboardMarkup:
    """Lokatsiya so'rash uchun klaviatura.

    Operator MIJOZ lokatsiyasini chat'dan FORWARD qiladi (mijoz uni avval
    Telegram'da yuborgan bo'lishi shart). "Mening joriy joyim" tugmasi ATAYLAB
    yo'q — operator o'z joyini emas, mijozникini yuboradi (aks holda buyurtma
    operatorning joylashuviga ketardi).
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CANCEL_ORDER)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Mijoz yuborgan lokatsiyani shu botga forward qiling",
    )


def cancel_only_kb() -> ReplyKeyboardMarkup:
    """Faqat bekor qilish — text input ekspektatsiyasi bilan."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL_ORDER)]],
        resize_keyboard=True,
    )


def products_picker_kb(products, cart: dict) -> InlineKeyboardMarkup:
    """Mahsulotlarni inline tugmalar bilan tanlash.

    Har mahsulot uchun bitta qator: [ −  Nom × N  + ]. Qator bosilsa miqdor
    o'zgaradi (callback `op:p:inc:<id>` / `op:p:dec:<id>`).
    Pastida "✅ Tugatdim" va "❌ Bekor" tugmalari.

    `cart` — `{food_id: quantity}`. UI har o'zgarishda qayta render qilinadi
    (eski message edit qilinadi).
    """
    rows = []
    for p in products:
        qty = cart.get(p.id, 0)
        min_q = int(getattr(p, "min_quantity", 1) or 1)
        label = f"{p.name} — {p.price}"
        if min_q > 1:
            label += f" (min {min_q})"
        if qty > 0:
            label = f"{p.name} × {qty}"
        rows.append([
            InlineKeyboardButton(text="➖", callback_data=f"op:p:dec:{p.id}"),
            InlineKeyboardButton(text=label, callback_data=f"op:p:info:{p.id}"),
            InlineKeyboardButton(text="➕", callback_data=f"op:p:inc:{p.id}"),
        ])
    if not rows:
        rows = [[InlineKeyboardButton(text="Mahsulot yo'q", callback_data="noop")]]
    # Pastki actions — har doim ko'rinadi
    total_qty = sum(cart.values())
    finish_text = f"✅ Tugatdim ({total_qty} ta)" if total_qty > 0 else "✅ Tugatdim"
    rows.append([
        InlineKeyboardButton(text=finish_text, callback_data="op:p:done"),
        InlineKeyboardButton(text="❌ Bekor", callback_data="op:p:cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_order_kb() -> InlineKeyboardMarkup:
    """Yakuniy tasdiqlash — "Yuborish" yoki "Bekor"."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Yuborish", callback_data="op:confirm:yes"),
            InlineKeyboardButton(text="❌ Bekor", callback_data="op:confirm:no"),
        ],
    ])
