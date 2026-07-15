"""Telefon raqami normalizatsiyasi — BUTUN TIZIM uchun yagona manba.

Muammo: mijoz '901234567', '+998 90 123 45 67', '998901234567' ko'rinishida
kiritadi — hammasi BITTA raqam. Identity qidiruvlari (user_phones.phone —
global unique) aynan tenglik bilan ishlaydi, shuning uchun barcha kirish
nuqtalari BIR XIL kanonik formatga keltirishi shart: +998XXXXXXXXX.

Qoidalar (tartib muhim):
  1. Ajratkichlar olib tashlanadi: bo'shliq, chiziqcha, qavslar.
  2. 9 raqam            → +998 qo'shiladi        (901234567 → +998901234567)
  3. 998 + 9 raqam (12) → + qo'shiladi           (998901234567 → +998901234567)
  4. 8998 + 9 raqam(13) → 8 tashlanadi, + (89989012345 67 kabi eski format)
  5. '+' bilan boshlansa → raqamlar tekshiriladi  (xalqaro format saqlanadi)
  6. Boshqasi           → invalid (jimgina '+' qo'shish o'chirildi — u
                          '+901234567' kabi hech qachon mos kelmaydigan
                          "yarim" raqamlar yaratardi)

JS ko'zgusi: webapp/static/js/format.js va webapp/admin_static/js/format.js
dagi `normalizePhone()` — qoidalarni o'zgartirsangiz, ikkalasini ham yangilang.
"""
from __future__ import annotations

import re
from typing import Optional

from Service.exceptions import ValidationError

# Yakuniy kanonik format: + va 9..15 raqam (E.164).
_CANONICAL_RE = re.compile(r"^\+\d{9,15}$")
# Kiritmadagi ruxsat etilgan ajratkichlar.
_SEPARATORS_RE = re.compile(r"[\s\-().]")


def normalize_phone(raw: str) -> str:
    """Kanonik +998XXXXXXXXX (yoki xalqaro +...) formatga keltiradi.

    Raises:
        ValidationError("phone_invalid") — bo'sh yoki tushunarsiz format.
    """
    s = _SEPARATORS_RE.sub("", (raw or "").strip())
    if not s:
        raise ValidationError("phone_invalid")

    had_plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits:
        raise ValidationError("phone_invalid")

    # O'zbekiston lokal format: 9 raqam (90 123 45 67).
    if len(digits) == 9 and not had_plus:
        return f"+998{digits}"
    # 998 bilan boshlangan to'liq format (+'siz terilgan).
    if len(digits) == 12 and digits.startswith("998"):
        return f"+{digits}"
    # Eski "8" prefiksli terish: 8 998 XX ... (ba'zi odatlar).
    if len(digits) == 13 and digits.startswith("8998"):
        return f"+{digits[1:]}"
    # Xalqaro format — '+' bilan aniq ko'rsatilgan.
    if had_plus:
        candidate = f"+{digits}"
        if _CANONICAL_RE.match(candidate):
            return candidate

    raise ValidationError("phone_invalid")


def normalize_phone_or_none(raw: Optional[str]) -> Optional[str]:
    """normalize_phone'ning None-toqatli varianti.

    None/bo'sh → None; noto'g'ri format → None (xato ko'tarmaydi) —
    qidiruv/lookup oqimlari uchun ("topilmadi" semantikasi).
    """
    if raw is None or not str(raw).strip():
        return None
    try:
        return normalize_phone(str(raw))
    except ValidationError:
        return None


def normalize_phone_lenient(raw: Optional[str]) -> str:
    """Buyurtma contact_phone uchun: normallashtirishga urinadi, bo'lmasa
    tozalangan xom matnni qaytaradi (kesilgan, 20 belygacha).

    contact_phone identity kaliti EMAS (faqat displey/tel: link) — noto'g'ri
    formatli raqam sababli buyurtmani rad etish noto'g'ri bo'lardi.
    """
    normalized = normalize_phone_or_none(raw)
    if normalized:
        return normalized
    return (raw or "").strip()[:20]
