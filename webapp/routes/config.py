"""Mini App uchun kompozit konfiguratsiya endpoint'i.

Frontend bootstrap'da chaqiradi va shu javobdan TTL, currency, brand, status
kataloglarini oladi. Bu — magic raqamlarni client kodidan olib tashlaydi va
yangilanish uchun rebuild kerak bo'lmaydi.
"""
from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from Domain.enums import OrderStatus
from webapp.deps import get_brand_name, telegram_user
from webapp.auth import TelegramUser

router = APIRouter(prefix="/api/config", tags=["config"])


class StatusInfo(BaseModel):
    code: str        # "NEW"
    token: str       # "new"  (CSS class — `status-pill--new`)
    label: str       # "Yangi"
    emoji: str       # "🆕"
    is_active: bool
    is_terminal: bool


class ConfigOut(BaseModel):
    brand_name: str
    currency_symbol: str
    locale: str
    # Cache TTL'lari (ms) — frontend api.js shu yerdan o'qiydi.
    cache_ttl_ms: Dict[str, int]
    # Buyurtma cheklovlari
    max_quantity_per_item: int
    max_items_per_order: int
    max_note_length: int
    # Eslatma: minimal buyurtma endi per-mahsulot (`ProductOut.min_quantity`).
    # Status katalogi — frontend timeline/pill rendiringi uchun
    statuses: List[StatusInfo]


def _all_statuses() -> List[StatusInfo]:
    return [
        StatusInfo(
            code=s.name,
            token=s.color_token,
            label=s.label_uz,
            emoji=s.emoji,
            is_active=s.is_active,
            is_terminal=s.is_terminal,
        )
        for s in OrderStatus
    ]


@router.get("", response_model=ConfigOut)
async def get_config(
    _user: TelegramUser = Depends(telegram_user),
    brand: str = Depends(get_brand_name),
) -> ConfigOut:
    from Domain.constants import (
        MAX_ITEMS_PER_ORDER,
        MAX_NOTE_LENGTH,
        MAX_QUANTITY_PER_ITEM,
    )
    from config import get_settings
    settings = get_settings()
    return ConfigOut(
        brand_name=brand,
        currency_symbol=settings.currency_symbol,
        locale=settings.locale,
        cache_ttl_ms={
            "me":       300_000,
            "products": 120_000,
            "product":  120_000,
            "orders":    15_000,
            "order":     10_000,
            "config":   600_000,
        },
        max_quantity_per_item=MAX_QUANTITY_PER_ITEM,
        max_items_per_order=MAX_ITEMS_PER_ORDER,
        max_note_length=MAX_NOTE_LENGTH,
        statuses=_all_statuses(),
    )
