"""Admin auth endpointi — `/me` (sessiya borligini va rolni qaytaradi).

Telegram Mini App `initData` orqali ishlaganligi sababli logout endpointi
kerak emas (har so'rov mustaqil verify qilinadi). `/me` bootstrap'da
chaqiriladi — UI foydalanuvchi rolini bilib, mos sahifalarni ko'rsatadi.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from webapp.admin.auth import operator_required, role_of
from webapp.auth import TelegramUser
from webapp.deps import AppContainer, _container

router = APIRouter(prefix="/api/admin/auth", tags=["admin:auth"])


@router.get("/me")
async def auth_me(
    user: TelegramUser = Depends(operator_required),
    c: AppContainer = Depends(_container),
) -> dict:
    """Joriy foydalanuvchining role'i va ma'lumotlari.

    `role` — "admin" yoki "operator". Mini App shu asosida UI'ni quradi:
      * admin    — to'liq dashboard, settings, products CRUD, finance, ...
      * operator — faqat "Yangi buyurtma" + "Mening buyurtmalarim"
    """
    return {
        "telegram_id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "username": user.username,
        "role": await role_of(user.id, c),
    }
