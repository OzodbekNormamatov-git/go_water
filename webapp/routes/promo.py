"""Mijoz Mini App — promokod kiritish (uyma-uy ishchisi uchun).

Oqim: promouter mijoznikiga boradi, botni tushuntiradi, manzil saqlashga
o'rgatadi, so'ng MIJOZNING telefonida, uning ruxsati bilan, o'z kodini kiritadi.
Shuning uchun bu endpoint MIJOZ sifatida autentifikatsiya qilinadi
(`telegram_user`) — promouterning alohida hisobi/login'i yo'q.

Endpoints:
  GET  /api/me/promo  — holat: kod kiritish mumkinmi, sabab nima
  POST /api/me/promo  — kodni faollashtirish

`GET` faqat UI'ni gate qilish uchun MASLAHAT beradi. Yakuniy qaror har doim
`POST` ichida, serverda, qaytadan tekshiriladi (frontend'ga ishonilmaydi).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from Domain.constants import PROMO_CODE_MAX_LENGTH
from Service.exceptions import DomainError, InvalidOperationError, ValidationError
from Service.promoter_service import PromoterService
from webapp.deps import get_promoter_service, telegram_user

router = APIRouter(prefix="/api/me/promo", tags=["promo"])


class PromoStatusOut(BaseModel):
    """Mijozning promokod holati — Mini App shu asosda UI ko'rsatadi."""
    program_enabled: bool
    eligible: bool
    already_redeemed: bool
    redeemed_code: str = ""
    has_orders: bool
    has_address: bool
    # i18n kaliti (`eligible=True` bo'lsa "") — frontend tushuntirish matnini
    # shu asosda tanlaydi (masalan, "avval manzil saqlang").
    reason: str = ""


class PromoRedeemIn(BaseModel):
    code: str = Field(min_length=1, max_length=PROMO_CODE_MAX_LENGTH + 8)


class PromoRedeemOut(BaseModel):
    ok: bool = True
    promo_code: str
    bonus_window_ends_at: datetime


@router.get("", response_model=PromoStatusOut)
async def promo_status(
    user=Depends(telegram_user),
    promoters: PromoterService = Depends(get_promoter_service),
) -> PromoStatusOut:
    try:
        e = await promoters.eligibility(user.id)
    except InvalidOperationError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    return PromoStatusOut(
        program_enabled=e.program_enabled,
        eligible=e.eligible,
        already_redeemed=e.already_redeemed,
        redeemed_code=e.redeemed_code,
        has_orders=e.has_orders,
        has_address=e.has_address,
        reason=e.reason,
    )


@router.post("", response_model=PromoRedeemOut)
async def redeem_promo(
    payload: PromoRedeemIn,
    user=Depends(telegram_user),
    promoters: PromoterService = Depends(get_promoter_service),
) -> PromoRedeemOut:
    """Promokodni mijoz hisobida faollashtiradi.

    Shartlar (serverda qayta tekshiriladi): dastur yoqiq, kod mavjud va ishchi
    aktiv, mijoz avval kod kiritmagan, mijozda 0 ta zakaz, >= 1 saqlangan manzil.
    """
    try:
        red = await promoters.redeem(user.id, payload.code)
    except (ValidationError, InvalidOperationError) as e:
        # Barcha shart buzilishlari 400 — xabar matni i18n'dan (o'zbekcha).
        raise HTTPException(status_code=400, detail=str(e))
    except DomainError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PromoRedeemOut(
        promo_code=red.promo_code,
        bonus_window_ends_at=red.bonus_window_ends_at,
    )
