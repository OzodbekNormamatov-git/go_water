"""Telegram WebApp `initData` HMAC-SHA256 tekshiruvi.

Telegram har bir Mini App ochilishida qo'shimcha `initData` query string
(yoki `WebApp.initData` JS property) yuboradi. Server `bot_token` orqali
HMAC ni qayta hisoblab, foydalanuvchi haqiqatan Telegram'dan kelganini
tasdiqlaydi. Bu — bizning yagona autentifikatsiya manbamiz.

Qoidalar (rasmiy hujjatdan):
  1. `data_check_string` — barcha kalit-qiymatlardan `key=value` ko'rinishida,
     `hash` dan tashqari, alfavit bo'yicha tartiblanib, `\\n` bilan birlashtiriladi.
  2. `secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)`.
  3. `expected = HEX(HMAC_SHA256(key=secret_key, msg=data_check_string))`.
  4. `expected == initData["hash"]` bo'lsa — sahih.

Ushbu modul `auth_date` ning yangiligini ham tekshiradi (default: 24 soat) —
eski/qayta o'ynatilgan initData'lar rad etiladi.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import parse_qsl

log = logging.getLogger(__name__)


# initData ning yaroqlilik muddati: undan keyin replay deb hisoblanadi.
DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60


class InitDataError(Exception):
    """initData noto'g'ri yoki muddati o'tgan."""


@dataclass(frozen=True, slots=True)
class TelegramUser:
    """Telegram'dan tasdiqlangan foydalanuvchi (initData[user] dan ajratilgan)."""

    id: int
    first_name: str
    last_name: str = ""
    username: Optional[str] = None
    language_code: Optional[str] = None
    is_premium: bool = False
    photo_url: Optional[str] = None

    @property
    def full_name(self) -> str:
        parts = [self.first_name.strip(), self.last_name.strip()]
        return " ".join(p for p in parts if p)


# Rasmiy Telegram hujjati va asosiy SDK'lar (`python-telegram-bot`,
# `telegram-apps`) faqat `hash` ni chiqarib tashlaydi — boshqa hamma maydonlar
# (`signature`, `chat_instance`, `chat_type` va h.k.) data_check_string'ga
# kiritiladi.
def _build_data_check_string(parsed: Dict[str, str]) -> str:
    items = sorted(
        (k, v) for k, v in parsed.items() if k != "hash"
    )
    return "\n".join(f"{k}={v}" for k, v in items)


def verify_init_data(
    init_data: str,
    *,
    bot_token: str,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> TelegramUser:
    """initData ni tekshiradi va `TelegramUser` qaytaradi.

    Xatolar:
        InitDataError — har qanday tekshiruv muvaffaqiyatsiz bo'lsa.
    """
    if not init_data:
        raise InitDataError("initData bo'sh.")
    if not bot_token:
        raise InitDataError("Server tomonida bot_token sozlanmagan.")

    # `keep_blank_values=True` — Telegram bo'sh `start_param=` ham yuboradi.
    parsed = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))

    received_hash = parsed.get("hash")
    if not received_hash:
        raise InitDataError("initData ichida hash yo'q.")

    data_check_string = _build_data_check_string(parsed)

    secret_key = hmac.new(
        key=b"WebAppData",
        msg=bot_token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    expected_hash = hmac.new(
        key=secret_key,
        msg=data_check_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        # `compare_digest` — timing attack'larga qarshi.
        raise InitDataError("initData imzo (hash) noto'g'ri.")

    # auth_date — tashqaridan kelgan, lekin endi imzosi tasdiqlangan, ishonsa bo'ladi.
    auth_date_raw = parsed.get("auth_date")
    if not auth_date_raw or not auth_date_raw.isdigit():
        raise InitDataError("initData ichida auth_date yo'q.")
    auth_date = int(auth_date_raw)
    age = int(time.time()) - auth_date
    if age < 0:
        # Soat noto'g'ri — kelajakdagi vaqt
        raise InitDataError("initData kelajakdagi vaqtga ega (soat noto'g'rimi?).")
    if age > max_age_seconds:
        raise InitDataError("initData muddati o'tgan, qaytadan oching.")

    user_raw = parsed.get("user")
    if not user_raw:
        raise InitDataError("initData ichida user yo'q.")
    try:
        user_obj = json.loads(user_raw)
    except json.JSONDecodeError as e:
        raise InitDataError(f"user JSON xato: {e}") from e

    user_id = user_obj.get("id")
    if not isinstance(user_id, int):
        raise InitDataError("user.id butun son emas.")

    return TelegramUser(
        id=user_id,
        first_name=str(user_obj.get("first_name", "") or ""),
        last_name=str(user_obj.get("last_name", "") or ""),
        username=user_obj.get("username"),
        language_code=user_obj.get("language_code"),
        is_premium=bool(user_obj.get("is_premium", False)),
        photo_url=user_obj.get("photo_url"),
    )
