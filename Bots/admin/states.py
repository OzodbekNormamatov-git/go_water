from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class FoodCreate(StatesGroup):
    name = State()
    description = State()
    price = State()
    photo = State()


class FoodEdit(StatesGroup):
    field_value = State()


class FoodPriceEdit(StatesGroup):
    value = State()


class OperatorOrder(StatesGroup):
    """Operator/Admin chat orqali yangi buyurtma yaratish oqimi.

    Asosiy maqsad: mijoz qo'ng'iroq qilganda operator uning lokatsiyasini
    Telegram orqali forward qilib (yoki contact share orqali) tezda buyurtma
    kiritishi mumkin. Mini App ko'rinishidan farqi — bu yerda barcha qadamlar
    chat xabarlari orqali ketadi.

    Oqim (7 qadam):
      1. waiting_phone        — mijoz telefoni (text yoki forwarded contact)
      2. waiting_name         — yangi mijoz uchun ism (eski mijozlarda skip)
      3. waiting_location     — yetkazib berish lokatsiyasi (forward yoki share)
      4. waiting_details      — manzil tafsilotlari (podyezd, kvartira)
      5. waiting_products     — mahsulot tanlash (inline kb + / −, "Tugatdim")
      6. waiting_contact_phone — kuryer uchun aloqa telefoni (`=` mijoz raqami)
      7. waiting_note         — buyurtmaga izoh
      8. confirming           — yakuniy ko'rib chiqish va tasdiqlash
    """
    waiting_phone = State()
    waiting_name = State()
    waiting_location = State()
    waiting_details = State()
    waiting_products = State()
    waiting_contact_phone = State()
    waiting_note = State()
    confirming = State()
