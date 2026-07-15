"""Promokod normalizatsiyasi va generatsiyasi — BUTUN TIZIM uchun yagona manba.

Muammo (`Service/phone.py` bilan bir xil sinf): kod QO'LDA kiritiladi —
promouter mijozning telefonida teradi, kod vizitka/varaqadan o'qiladi yoki
og'zaki aytiladi. Bitta kod turlicha yozilishi mumkin:
    'ab-12cd', 'AB 12 CD', 'ab12cd'  →  hammasi BITTA kod.

`promoters.promo_code` UNIQUE va aynan TENGLIK bilan qidiriladi, shuning uchun
barcha kirish nuqtalari (mijoz Mini App'i, admin paneli) bir xil kanonik
formatga keltirishi shart: UPPERCASE, ajratkichlarsiz.

Alifbo — `Domain/constants.py:PROMO_CODE_ALPHABET`: chalkashadigan belgilar
ATAYLAB chiqarilgan (O↔0, I↔1↔L). Bu "kod ishlamayapti" shikoyatlarining eng
keng tarqalgan sababini yo'q qiladi.

Layering eslatmasi: `Data/` bu modulni import QILMAYDI (N-tier). Repository
tayyor, normalizatsiyalangan qiymat kutadi — normalizatsiya doim shu qatlamda.
"""
from __future__ import annotations

import re
import secrets

from Domain.constants import (
    PROMO_CODE_ALLOWED,
    PROMO_CODE_ALPHABET,
    PROMO_CODE_GENERATED_LENGTH,
    PROMO_CODE_MAX_LENGTH,
    PROMO_CODE_MIN_LENGTH,
)
from Service.exceptions import ValidationError

# Kiritmada ruxsat etilgan (va tashlab yuboriladigan) ajratkichlar.
_SEPARATORS_RE = re.compile(r"[\s\-_().]")

# QABUL qilinadigan belgilar (to'liq A-Z0-9) — tez tekshiruv uchun frozenset.
# DIQQAT: bu `PROMO_CODE_ALPHABET` EMAS. Alifbo faqat avtomatik generatsiya
# uchun tor (O/0/I/1/L siz); admin qo'lda "OLIM01" kabi kod bera olishi kerak.
_ALLOWED = frozenset(PROMO_CODE_ALLOWED)


def normalize_promo_code_lenient(raw: str | None) -> str:
    """Kanonik ko'rinishga keltiradi, XATO BERMAYDI — mos kelmasa "" qaytaradi.

    MIJOZ kod kiritayotganda ishlatiladi. Nega xato bermaydi: mijozga
    "format noto'g'ri" va "bunday kod yo'q" ni ajratib ko'rsatish keraksiz
    (va zararli — kod formatini fosh qiladi). Ikkalasi ham bitta tushunarli
    xabar bilan tugaydi: `promo_code_invalid`.
    """
    s = _SEPARATORS_RE.sub("", (raw or "").strip()).upper()
    if not s:
        return ""
    if len(s) < PROMO_CODE_MIN_LENGTH or len(s) > PROMO_CODE_MAX_LENGTH:
        return ""
    if not set(s) <= _ALLOWED:
        return ""
    return s


def normalize_promo_code(raw: str | None) -> str:
    """Kanonik ko'rinishga keltiradi va QAT'IY tekshiradi.

    ADMIN yangi promouterga kod berayotganda ishlatiladi — admin xatoning
    aniq sababini bilishi kerak (mijozdan farqli).

    Raises:
        ValidationError("promo_code_required")        — bo'sh.
        ValidationError("promoter_code_length")       — uzunlik chegaradan tashqari.
        ValidationError("promoter_code_charset")      — taqiqlangan belgi bor.
    """
    s = _SEPARATORS_RE.sub("", (raw or "").strip()).upper()
    if not s:
        raise ValidationError("promo_code_required")
    if len(s) < PROMO_CODE_MIN_LENGTH or len(s) > PROMO_CODE_MAX_LENGTH:
        raise ValidationError(
            "promoter_code_length",
            context={"min": PROMO_CODE_MIN_LENGTH, "max": PROMO_CODE_MAX_LENGTH},
        )
    bad = sorted(set(s) - _ALLOWED)
    if bad:
        raise ValidationError(
            "promoter_code_charset", context={"chars": " ".join(bad)},
        )
    return s


def generate_promo_code(length: int = PROMO_CODE_GENERATED_LENGTH) -> str:
    """Tasodifiy kod yaratadi (admin qo'lda kod bermasa).

    `secrets` — `random` EMAS: kod taxmin qilinadigan bo'lmasligi kerak. Aks
    holda mijoz keyingi kodni topib, promouter kelmasdan turib "o'ziga o'zi"
    kod kiritib qo'yishi mumkin edi.

    Noyoblik BU YERDA kafolatlanmaydi — chaqiruvchi (PromoterService) DB'da
    band emasligini tekshiradi va bandi chiqsa qayta uradi. Yakuniy kafolat —
    `promoters.promo_code` ustunidagi UNIQUE constraint.
    """
    n = max(PROMO_CODE_MIN_LENGTH, min(length, PROMO_CODE_MAX_LENGTH))
    return "".join(secrets.choice(PROMO_CODE_ALPHABET) for _ in range(n))
