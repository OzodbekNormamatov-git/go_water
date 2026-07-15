"""Admin Mini App auth — Telegram initData HMAC + role tekshiruvi.

Rollar:
  * admin    — to'liq huquq (Settings, Products CRUD/tannarx, Kuryerlar,
               Operatorlar, Moliya/Rasxodlar, balans tahrirlash, ledger,
               telefon o'chirish/asosiy qilish, buyurtma bekor qilish, ...)
  * operator — "Yangi buyurtma" + buyurtmalar (faqat o'zi yaratganlari) +
               Aqlli eslatma + Mijozlar (qidirish/qo'shish, telefon ko'rish/
               qo'shish). Moliyaviy balanslar ro'yxatda 0 qilib berkitiladi;
               balans/ledger/o'chirish amallariga kira olmaydi.

Foydalanish (route'da):
    user = Depends(admin_required)     # faqat admin
    user = Depends(operator_required)  # admin OR aktiv operator (DB'dan)
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import Depends, Header, HTTPException, Request, status

from webapp.auth import InitDataError, TelegramUser, verify_init_data
from webapp.deps import AppContainer, _container

log = logging.getLogger(__name__)

_AUTH_PREFIX = "tma "

Role = Literal["admin", "operator"]


def _verify_init_data(
    request: Request, authorization: Optional[str], c: AppContainer,
) -> TelegramUser:
    """Telegram initData HMAC tekshiruvi — har ikki rol uchun umumiy."""
    if not authorization or not authorization.lower().startswith(_AUTH_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization yo'q. Mini App'ni Telegram'dan oching.",
            headers={"WWW-Authenticate": 'tma realm="admin"'},
        )
    init_data = authorization[len(_AUTH_PREFIX):].strip()
    try:
        return verify_init_data(init_data, bot_token=c.admin_bot_token)
    except InitDataError:
        log.info("Admin initData rad etildi ip=%s", request.client.host if request.client else "?")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessiya yaroqsiz. Mini App'ni qaytadan oching.",
        )


async def role_of(user_id: int, c: AppContainer) -> Optional[Role]:
    """Foydalanuvchining rolini aniqlaydi: "admin" / "operator" / None.

    Admin — .env whitelist (DB'ga bog'liq emas, lockout'dan himoya).
    Operator — `operators` jadvalidagi AKTIV qator (admin boshqaradi,
    restart shart emas). Admin'lik operator'likdan ustun.
    """
    uid = int(user_id)
    if uid in {int(x) for x in c.admin_telegram_ids}:
        return "admin"
    if await c.operator_service.is_active_operator(uid):
        return "operator"
    return None


async def admin_required(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    c: AppContainer = Depends(_container),
) -> TelegramUser:
    """Faqat admin role'iga ruxsat. Operator'larga 403."""
    user = _verify_init_data(request, authorization, c)
    if await role_of(user.id, c) != "admin":
        log.warning("Admin bo'lmagan user admin endpoint'iga kirishga urindi: tg=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sizga admin paneliga to'liq kirish ruxsati berilmagan.",
        )
    return user


async def operator_required(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    c: AppContainer = Depends(_container),
) -> TelegramUser:
    """Admin yoki AKTIV operator role'iga ruxsat. Boshqalarga 403."""
    user = _verify_init_data(request, authorization, c)
    if await role_of(user.id, c) is None:
        log.warning("Notanish user admin/operator endpoint'iga kirishga urindi: tg=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sizga kirish ruxsati berilmagan.",
        )
    return user
