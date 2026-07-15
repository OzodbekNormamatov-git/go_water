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

# ---------------------- Promouterlar (uyma-uy ishchilar) ----------------------
# Promokod formati. Ikkita ALOHIDA alifbo — ataylab:
#
#   PROMO_CODE_ALLOWED  — QABUL qilinadigan belgilar (validatsiya). To'liq
#     A-Z0-9: admin xohlagan mazmunli kodni bera olsin ("OLIM01", "ALI1").
#     Cheklash bu yerda faqat bezovta qilardi — kodni admin o'zi tanlaydi.
#
#   PROMO_CODE_ALPHABET — AVTOMATIK yaratishda ishlatiladigan tor to'plam.
#     Chalkashadigan belgilar chiqarilgan: O↔0 va I↔1↔L. Sabab: avtomatik kod
#     og'zaki aytiladi/vizitkadan ko'chiriladi, va "0 mi, O mi?" degan savol
#     "kod ishlamayapti" shikoyatlarining eng keng tarqalgan sababi.
PROMO_CODE_ALLOWED: Final[str] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
PROMO_CODE_ALPHABET: Final[str] = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
PROMO_CODE_MIN_LENGTH: Final[int] = 4
PROMO_CODE_MAX_LENGTH: Final[int] = 16
# Admin qo'lda kod bermasa — shu uzunlikda avtomatik generatsiya qilinadi.
PROMO_CODE_GENERATED_LENGTH: Final[int] = 6

# Bonus (KPI) default sozlamalari — `AppSettings` birinchi yaratilganda.
# Live qiymatlar admin Mini App "Sozlamalar" bo'limidan boshqariladi.
# Default 0: dastur yoqilgan bo'lsa-da, admin summani ataylab belgilamaguncha
# hech kimga pul yozilmaydi (tasodifiy xarajatdan himoya).
DEFAULT_PROMOTER_BONUS_PER_ORDER: Final[int] = 0
MAX_PROMOTER_BONUS_PER_ORDER: Final[int] = 1_000_000
# Promokod kiritilgandan keyin necha kun davomida mijozning zakazlari
# promouterga bonus keltiradi. Davr `promoter_redemptions.bonus_window_ends_at`
# ga MUHRLANADI (keyingi sozlama o'zgarishi eskilarga ta'sir qilmaydi).
DEFAULT_PROMOTER_BONUS_WINDOW_DAYS: Final[int] = 90
MIN_PROMOTER_BONUS_WINDOW_DAYS: Final[int] = 1
MAX_PROMOTER_BONUS_WINDOW_DAYS: Final[int] = 3650

# ---------------------- Rasxodlar (expenses) ----------------------
# Doimiy rasxod materializatsiyasi eng ko'pi shuncha kun ORQAGA qaraydi —
# juda eski start_date bilan ming-minglab qator yaratilib ketmasin (himoya).
EXPENSE_MATERIALIZE_LOOKBACK_DAYS: Final[int] = 730
