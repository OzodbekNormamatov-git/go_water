from __future__ import annotations

from typing import Iterable

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message


class IsAdminFilter(BaseFilter):
    """Faqat admin role'iga ruxsat (env whitelist).

    Admin-only handler'larga (mahsulot CRUD, buyurtmalar, kuryerlar) qo'shiladi —
    operator bu tugma matnini qo'lda tersa ham handler ishga tushmaydi.
    """

    def __init__(self, admin_ids: Iterable[int]) -> None:
        self._admin_ids = set(int(x) for x in admin_ids)

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        return bool(user and user.id in self._admin_ids)


class AdminBotAccessFilter(BaseFilter):
    """Dispatcher darajasidagi kirish nazorati (admin bot).

    * Admin (env whitelist)          — barcha handler'lar.
    * AKTIV operator (DB, operators) — o'z handler'lari (admin-only'lar
      IsAdminFilter bilan alohida himoyalangan).
    * Notanish user                  — FAQAT /start (o'zini operator sifatida
      ro'yxatga olish uchun; kuryer bot patterni). Boshqa hamma update drop.

    Operator tekshiruvi DB'dan (indeksli SELECT) — admin .env'ni tahrirlashsiz
    va restart'siz operator qo'shadi/o'chiradi.
    """

    def __init__(self, admin_ids: Iterable[int], operator_service) -> None:
        self._admin_ids = set(int(x) for x in admin_ids)
        self._operators = operator_service

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        if user is None:
            return False
        if user.id in self._admin_ids:
            return True
        if await self._operators.is_active_operator(user.id):
            return True
        # Notanish user — faqat /start'ga ruxsat (ro'yxatdan o'tish oqimi).
        if isinstance(event, Message):
            text = (event.text or "").strip()
            if text.startswith("/start"):
                return True
        return False


class AdminCallbackGuard(BaseFilter):
    """`adm:*` callback'lari faqat admin uchun (dispatcher darajasida AND filter).

    Operator admin inline tugmalarini (eski xabardan yoki soxta client'dan)
    bossa — update jimgina tashlanadi. Boshqa callback'larga ta'sir qilmaydi.
    """

    def __init__(self, admin_ids: Iterable[int]) -> None:
        self._admin_ids = set(int(x) for x in admin_ids)

    async def __call__(self, cb: CallbackQuery) -> bool:
        data = cb.data or ""
        if not data.startswith("adm:"):
            return True
        return bool(cb.from_user and cb.from_user.id in self._admin_ids)
