"""Vaqt yordamchilari — mahalliy (Toshkent) timezone.

Yangi kod shu yagona helper'dan foydalanadi. (Eski 4-5 nusxani shu yerga
ko'chirish — alohida refactor; import-sikl xavfi sababli ehtiyot bilan.)
"""
from __future__ import annotations

from datetime import timedelta, timezone
from zoneinfo import ZoneInfo


def local_tz():
    """Config'dagi timezone (default Asia/Tashkent). Topilmasa UTC+5 fallback."""
    try:
        from config import get_settings
        return ZoneInfo(get_settings().timezone)
    except Exception:
        return timezone(timedelta(hours=5))


def local_tz_name() -> str:
    """Timezone NOMI (PostgreSQL `timezone(...)` funksiyasi uchun).

    SQL'da kun/oy bucketlash mahalliy vaqtda bo'lishi kerak — nom string
    sifatida uzatiladi (ZoneInfo obyekti emas).
    """
    try:
        from config import get_settings
        return get_settings().timezone or "Asia/Tashkent"
    except Exception:
        return "Asia/Tashkent"
