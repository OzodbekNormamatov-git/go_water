"""Xato kodlari va localizatsiya lug'ati.

Service qatlami xato matnini emas, **kodini** qaytaradi. Bot/WebApp matnga
aylantiradi. Buning ustunligi:
  1. Yangi til qo'shilsa, faqat lug'atni yangilash kerak.
  2. Service'lar sof biznes mantiqda qoladi (UI text yo'q).
  3. Front-end ham kod orqali xatoga reaktsiya qila oladi.

Foydalanish:
    raise ValidationError(code="cart_empty")
    raise ValidationError(code="phone_invalid", phone=phone_value)

Bot/WebApp tomonda:
    from Service.i18n import translate
    msg = translate(err.code, locale="uz", **err.context)
"""
from __future__ import annotations

from typing import Dict


# Til ↦ kod ↦ shablon
_MESSAGES: Dict[str, Dict[str, str]] = {
    "uz": {
        # Cart / order
        "cart_empty":            "Savatcha bo'sh.",
        "cart_item_qty_invalid": "Mahsulot soni 0 dan katta bo'lishi kerak.",
        "cart_item_qty_too_big": "Bir mahsulotda {max} dan oshmasin.",
        "item_below_minimum":    "\"{name}\" uchun minimal buyurtma {min} dona. Iltimos, miqdorni oshiring.",
        "food_unavailable":      "Mahsulot #{food_id} hozir mavjud emas.",
        "food_not_found":        "Mahsulot topilmadi.",
        "order_not_found":       "Buyurtma topilmadi.",
        "order_already_closed":  "Buyurtma allaqachon yopilgan.",
        "order_not_yours":       "Bu buyurtma sizniki emas.",
        "order_state_invalid":   "Holatni o'zgartirib bo'lmaydi: {status}.",
        "order_already_claimed": "Buyurtmani allaqachon boshqa kuryer oldi yoki holati: {status}.",
        "note_empty":            "Buyurtmaga izoh kiritish majburiy.",
        # Location
        "location_required":     "Yetkazib berish manzili (lokatsiya) kerak.",
        "location_invalid":      "Lokatsiya koordinatalari noto'g'ri.",
        # Phone
        "phone_required":        "Aloqa telefoni kerak.",
        "phone_invalid":         "Telefon raqam noto'g'ri formatda. Masalan: +998901234567",
        "phone_taken":           "Bu telefon raqam boshqa hisobga biriktirilgan.",
        # User
        "user_not_registered":   "Avval ro'yxatdan o'ting (/start).",
        "name_too_short":        "Ism juda qisqa.",
        # Food (admin)
        "name_short":            "Nom juda qisqa.",
        "price_invalid":         "Narx noto'g'ri formatda.",
        "price_positive":        "Narx 0 dan katta bo'lishi kerak.",
        "food_min_qty_invalid":  "Minimal buyurtma soni {min} va {max} oralig'ida bo'lishi shart.",
        "food_bottles_per_unit_invalid": "Qaytariladigan idishlar soni {min} va {max} oralig'ida bo'lishi shart.",
        # Courier
        "courier_not_registered":         "Kuryer ro'yxatda yo'q.",
        "cash_amount_invalid":            "Naqd summa noto'g'ri.",
        "cash_settle_exceeds":            "Kuryerda atigi {available} so'm naqd bor — bundan ko'pini qabul qilib bo'lmaydi.",
        "courier_not_started_bot":        "Avval kuryer botiga shaxsiy yozib /start yuboring.",
        "courier_not_active":             "Hisobingiz hali aktivlashtirilmagan. Admin bilan bog'lanib, sizni aktiv qilib qo'yishini so'rang.",
        "courier_has_active_order":       "Sizda tugallanmagan buyurtma bor ({ids}). Avval uni yopib, keyin yangisini oling.",
        # Address book
        "address_label_required":         "Manzilga nom bering (masalan, \"Uy\").",
        "address_label_too_long":         "Manzil nomi juda uzun ({max} belgidan ko'p emas).",
        "address_details_too_long":       "Manzil tafsilotlari juda uzun ({max} belgidan ko'p emas).",
        "address_label_taken":            "Bu nomdagi manzil allaqachon mavjud. Boshqa nom tanlang.",
        "address_not_found":              "Manzil topilmadi.",
        "address_limit_reached":          "Manzillar soni cheklovga yetdi ({max} ta). Avvalgilaridan birini o'chiring.",
        # Cashback
        "cashback_not_enough":            "Hisobingizda yetarli keshbek yo'q (mavjud: {available}).",
        "cashback_over_limit":            "Bitta buyurtmada keshbek bilan eng ko'pi bilan {ratio_percent}% ulushni qoplash mumkin.",
        "cashback_negative":              "Keshbek miqdori manfiy bo'la olmaydi.",
        "cashback_disabled":              "Keshbek dasturi hozir o'chirilgan. Iltimos, keshbeksiz buyurtma bering.",
        # Settings (admin)
        "settings_percent_out_of_range":  "Keshbek foizi {min}% va {max}% oralig'ida bo'lishi shart.",
        "settings_ratio_out_of_range":    "Keshbek bilan qoplash chegarasi {min} va {max} oralig'ida bo'lishi shart.",
        "settings_lead_days_out_of_range": "Eslatma kuni {min} va {max} kun oralig'ida bo'lishi shart.",
        # Bottles
        "bottles_out_of_range":           "Idishlar soni 0..{max} oralig'ida bo'lishi shart.",
        "bottles_return_exceeds_balance": "Mijozda atigi {available} ta idish mavjud, {requested} ta qaytarib bo'lmaydi.",
        # Ledger (moliyaviy jurnal)
        "balance_negative":               "Balans manfiyga tushib ketadi (mavjud: {available}).",
        # Depozit (oldindan to'lov / avans) balansi
        "deposit_delta_invalid":          "Balans o'zgarishi 0 bo'lmagan son bo'lishi kerak.",
        "deposit_not_enough":             "Mijoz balansida yetarli mablag' yo'q (mavjud: {available} so'm).",
        "deposit_insufficient_for_order": "Balansda yetarli mablag' yo'q: kerak {required} so'm, mavjud {available} so'm.",
        # To'lov usuli
        "payment_method_invalid":         "To'lov usuli noto'g'ri (naqd/karta/balans).",
        "payment_method_locked_deposit":  "Balansdan to'langan buyurtma — to'lov usulini o'zgartirib bo'lmaydi.",
        # Broadcast
        "broadcast_body_required":        "Xabar matni bo'sh bo'la olmaydi.",
        "broadcast_body_too_long":        "Xabar matni juda uzun ({max} belgidan ko'p emas).",
        "broadcast_caption_too_long":     "Rasm bilan yuborilayotgan matn {max} belgidan ko'p bo'lmasligi kerak.",
        "broadcast_title_too_long":       "Sarlavha juda uzun ({max} belgidan ko'p emas).",
        "broadcast_not_found":            "Rassilka topilmadi.",
        "broadcast_already_running":      "Bu rassilka allaqachon yuborilmoqda.",
        # Telefon raqamlar (user_phones)
        "phone_not_found":                "Telefon raqam topilmadi.",
        "phone_primary_undeletable":      "Asosiy raqamni o'chirib bo'lmaydi — avval boshqa raqamni asosiy qiling.",
        "phone_limit_reached":            "Raqamlar soni cheklovga yetdi ({max} ta).",
        # Mahsulot tannarxi (COGS)
        "cost_price_invalid":             "Tannarx noto'g'ri formatda.",
        "cost_price_negative":            "Tannarx manfiy bo'la olmaydi.",
        # Rasxodlar (expenses)
        "expense_not_found":              "Rasxod yozuvi topilmadi.",
        "expense_category_not_found":     "Rasxod kategoriyasi topilmadi.",
        "expense_category_name_taken":    "Bu nomdagi kategoriya allaqachon mavjud.",
        "expense_category_has_recurring": "Bu kategoriyada aktiv doimiy rasxod bor — avval uni to'xtating.",
        "expense_recurring_not_found":    "Doimiy rasxod shabloni topilmadi.",
        "expense_recurring_date_locked":  "Doimiy rasxod yozuvining sanasini o'zgartirib bo'lmaydi.",
        "expense_amount_invalid":         "Rasxod summasi noto'g'ri formatda.",
        "expense_amount_positive":        "Rasxod summasi 0 dan katta bo'lishi kerak.",
        "expense_period_invalid":         "Davr noto'g'ri (monthly/weekly/yearly).",
        "expense_anchor_day_invalid":     "Kun {min} va {max} oralig'ida bo'lishi shart.",
        "expense_anchor_month_invalid":   "Oy {min} va {max} oralig'ida bo'lishi shart.",
        "expense_dates_invalid":          "Tugash sanasi boshlanish sanasidan oldin bo'la olmaydi.",
        # Operatorlar (admin bot)
        "operator_not_found":             "Operator topilmadi.",
        # Promouterlar (uyma-uy ishchilar) — mijoz tomoni
        "promo_code_required":            "Promokodni kiriting.",
        "promo_code_invalid":             "Bunday promokod topilmadi yoki u endi faol emas.",
        "promo_code_already_used":        "Bu hisobda promokod allaqachon kiritilgan.",
        "promo_code_customer_has_orders": "Promokod faqat hali birorta buyurtma bermagan mijozlar uchun amal qiladi.",
        "promo_code_no_address":          "Avval kamida bitta manzilni saqlang (masalan, \"Uy\"), keyin promokodni kiriting.",
        "promoter_program_disabled":      "Promokod dasturi hozir o'chirilgan.",
        # Promouterlar — admin tomoni
        "promoter_not_found":             "Promouter topilmadi.",
        "promoter_code_taken":            "\"{code}\" kodi allaqachon band. Boshqa kod tanlang.",
        "promoter_code_length":           "Promokod {min} va {max} ta belgi oralig'ida bo'lishi shart.",
        "promoter_code_charset":          "Promokodda ruxsat etilmagan belgi: {chars}. Faqat lotin harflari (A-Z) va raqamlar (0-9) mumkin.",
        "promoter_code_generation_failed": "Kod yaratib bo'lmadi. Qayta urinib ko'ring yoki kodni qo'lda kiriting.",
        "settings_promoter_bonus_out_of_range":  "Promouter bonusi 0 va {max} so'm oralig'ida bo'lishi shart.",
        "settings_promoter_window_out_of_range": "Bonus davri {min} va {max} kun oralig'ida bo'lishi shart.",
        # Aqlli eslatma (operator qo'ng'iroqlari)
        "call_outcome_invalid":           "Qo'ng'iroq natijasi noto'g'ri.",
        "snooze_too_long":                "Keyinga surish eng ko'pi {max} kun bo'lishi mumkin.",
        # Misc
        "internal_error":        "Server xatosi yuz berdi.",
    }
}

DEFAULT_LOCALE = "uz"


def translate(code: str, locale: str = DEFAULT_LOCALE, **context: object) -> str:
    """Xato kodini foydalanuvchi tilidagi matnga aylantiradi.

    Noma'lum kod bo'lsa kodning o'zi qaytariladi (degraded, lekin debug uchun
    foydali — nima yetishmayotganini ko'rasiz).
    """
    table = _MESSAGES.get(locale) or _MESSAGES[DEFAULT_LOCALE]
    template = table.get(code) or _MESSAGES[DEFAULT_LOCALE].get(code) or code
    try:
        return template.format(**context)
    except (KeyError, IndexError):
        return template
