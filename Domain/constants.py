"""Domain darajadagi konstantalar — biznes qoidalar.

Bu fayl framework-free, faqat Python. Ham bot, ham webapp ishlatadi.
Magic raqamlar va string'lar shu yerga ko'chiriladi.
"""
from __future__ import annotations

from typing import Final

# ---------------------- Buyurtma cheklovlari ----------------------
MAX_QUANTITY_PER_ITEM: Final[int] = 999
MIN_QUANTITY_PER_ITEM: Final[int] = 1
MAX_ITEMS_PER_ORDER: Final[int] = 50
MAX_NOTE_LENGTH: Final[int] = 500
# Eslatma: minimal buyurtma endi har mahsulotda alohida (`Food.min_quantity`,
# 1..MAX_QUANTITY_PER_ITEM). Ilgari global DEFAULT_MIN_ORDER_QUANTITY bor edi.

# Latitude/longitude chegaralari
LAT_MIN: Final[float] = -90.0
LAT_MAX: Final[float] = 90.0
LON_MIN: Final[float] = -180.0
LON_MAX: Final[float] = 180.0

# ---------------------- Manzillar xotirasi (Address Book) ----------------------
MAX_ADDRESSES_PER_USER: Final[int] = 10
MAX_ADDRESS_LABEL_LENGTH: Final[int] = 40
MAX_ADDRESS_DETAILS_LENGTH: Final[int] = 200

# ---------------------- Keshbek (Cashback) ----------------------
# Default qiymatlar — `AppSettings` jadvalida birinchi qator yaratilganda
# ishlatiladi. Live qiymatlar admin tomonidan o'zgartiriladi va DB'dan o'qiladi.
DEFAULT_CASHBACK_PERCENT: Final[float] = 1.5
DEFAULT_MAX_CASHBACK_USAGE_RATIO: Final[float] = 1.00  # to'liq qoplash mumkin
# Keshbekni hisoblashning birligi (mijoz QO'LGA OLAYOTGAN keshbek qadami).
# Misol: 1.5% of 47 230 = 708.45 → 700 (har 100 so'mga floor — mijozga foydali).
CASHBACK_ROUND_UNIT: Final[int] = 100

# Keshbekni ISHLATISH birligi — mijoz buyurtmada eng kam shuncha sumdan
# ko'paytirib qoplaydi. 1000 — slider step va minimal qoplash chegarasi.
# Misol: 1000, 2000, 5000 ✓; 1400, 5700 ✗ (floor to 1000).
CASHBACK_USE_UNIT: Final[int] = 1000

# ---------------------- Idishlar (bottle) hisobi ----------------------
# Bir buyurtmada qaytarilishi mumkin bo'lgan idishlar maksimumi
# (mijoz tasodifan katta son kiritmasin uchun himoya).
MAX_BOTTLES_PER_TRANSACTION: Final[int] = 50
# Bir buyurtmada BERILADIGAN idishlar sanity cap'i (katta buyurtmalar
# qonuniy ravishda 50 dan oshishi mumkin — lekin absurd qiymat kirmasin).
# create_order avto-hisobida ham, kuryer qo'lda kiritishida ham ishlatiladi.
MAX_BOTTLES_ISSUED_PER_ORDER: Final[int] = MAX_BOTTLES_PER_TRANSACTION * 10

# Har bir mahsulot DONASIGA to'g'ri keladigan qaytariladigan idishlar soni
# (`Food.bottles_per_unit`). 0 = sanalmaydi (pumpa, kuller, filtr), 1 = oddiy
# idish (suv baklashkasi), N = multi-pack (masalan, 6-li yashik). DELIVERED
# bo'lganda mijoz idish balansiga shu son × dona qo'shiladi.
MAX_BOTTLES_PER_UNIT: Final[int] = 99

# ---------------------- Avto-eslatma (predictive reorder) ----------------------
# Mijozning iste'mol tezligiga qarab "suv kerakmi?" eslatmasi.
# Hisoblangan sikl shu chegaralarga qisiladi (absurd qiymatlardan himoya).
REMINDER_MIN_CYCLE_DAYS: Final[int] = 2
REMINDER_MAX_CYCLE_DAYS: Final[int] = 60
# Shaxsiy sikl uchun kamida shuncha DELIVERED suv-buyurtma kerak (aks holda
# global o'rtacha tezlik ishlatiladi).
REMINDER_MIN_ORDERS_FOR_CADENCE: Final[int] = 2
# Bitta buyurtmadan keyin eng ko'pi shuncha eslatma — keyin to'xtaydi (churn).
REMINDER_MAX_PER_ORDER: Final[int] = 2
# Eslatma yuboriladigan mahalliy soat (Toshkent) — DOIM kunning birinchi yarmida
# (kechqurun emas: kuryerlar mavjud bo'lsin). Hisob faqat KUNLARDA, soatlarda emas.
REMINDER_SEND_HOUR_LOCAL: Final[int] = 10
# Admin sozlamasi default: sikl tugashidan necha kun OLDIN eslatma (0 = aynan kuni).
DEFAULT_REMINDER_LEAD_DAYS: Final[int] = 1
# Global default per-idish-kun (1 ta ham interval bo'lmasa, eng oxirgi fallback).
DEFAULT_PER_BOTTLE_DAYS: Final[float] = 7.0

# ---------------------- Broadcast / Rassilka ----------------------
MAX_BROADCAST_TITLE_LENGTH: Final[int] = 80
MAX_BROADCAST_BODY_LENGTH: Final[int] = 3500
# Yuborish oralig'i — Telegram per-bot rate limit (~30 msg/sec) ga moslab.
BROADCAST_SEND_DELAY_SECONDS: Final[float] = 0.05

# ---------------------- Telefon raqamlar (user_phones) ----------------------
# Bir mijozga biriktirilishi mumkin bo'lgan raqamlar maksimumi (sanity cap).
MAX_PHONES_PER_USER: Final[int] = 10

# ---------------------- Aqlli eslatma (operator paneli) ----------------------
# "Suv olish vaqti kelgan mijozlar" — operator qo'ng'iroq qiladigan ro'yxat.
# Sikl tugagandan keyin necha kun o'tsa OVERDUE → CHURNED (default; admin
# `app_settings.reorder_churn_after_days` orqali o'zgartiradi).
DEFAULT_CHURN_AFTER_DAYS: Final[int] = 14
# Operator "keyinroq chaqirish" (snooze) maksimal muddati.
MAX_REORDER_SNOOZE_DAYS: Final[int] = 90

# ---------------------- Rasxodlar (expenses) ----------------------
# Doimiy rasxod materializatsiyasi eng ko'pi shuncha kun ORQAGA qaraydi —
# juda eski start_date bilan ming-minglab qator yaratilib ketmasin (himoya).
EXPENSE_MATERIALIZE_LOOKBACK_DAYS: Final[int] = 730
