"""Admin — Promouterlar (uyma-uy ishchilar) boshqaruvi va KPI.

FAQAT ADMIN (`admin_required`) — operatorlar kira olmaydi. Sabab: bu yerda
bonus = pul; operator huquqi mahsulot/buyurtma darajasida qoladi.

Endpoints:
  GET    /api/admin/promoters                 — ro'yxat + KPI (sahifalangan)
  POST   /api/admin/promoters                 — yangi promouter (kod ixtiyoriy)
  GET    /api/admin/promoters/{id}            — bitta promouter + KPI
  PATCH  /api/admin/promoters/{id}            — ism/telefon/aktivlik
  DELETE /api/admin/promoters/{id}            — arxivlash (soft delete)
  POST   /api/admin/promoters/{id}/restore    — arxivdan qaytarish
  GET    /api/admin/promoters/{id}/customers  — jalb qilingan mijozlar

Promokod `PATCH` da ATAYLAB YO'Q — kod o'zgarmas (zakazlarga snapshot bo'lib
muhrlangan va bosma materiallarda tarqalgan).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from Domain.constants import PROMO_CODE_MAX_LENGTH
from Service.exceptions import DomainError, EntityNotFoundError, ValidationError
from Service.promoter_service import PromoterService
from webapp.admin.auth import admin_required
from webapp.deps import get_promoter_service
from webapp.pagination import Page

router = APIRouter(prefix="/api/admin/promoters", tags=["admin:promoters"])


# ---------------------- Schemas ----------------------

class PromoterOut(BaseModel):
    id: int
    full_name: str
    phone_number: Optional[str] = None
    promo_code: str
    is_active: bool
    is_archived: bool
    created_at: datetime
    # Jalb qilingan mijozlar (promokod kiritganlar) soni.
    customers: int
    # KPI — YETKAZILGAN (DELIVERED) zakazlar soni va jami bonus.
    delivered_orders: int
    bonus_total: Decimal


class PromoterCreateIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone_number: Optional[str] = Field(default=None, max_length=32)
    # Bo'sh qoldirilsa — avtomatik, noyob kod generatsiya qilinadi.
    promo_code: Optional[str] = Field(default=None, max_length=PROMO_CODE_MAX_LENGTH)


class PromoterUpdateIn(BaseModel):
    """`promo_code` YO'Q — kod o'zgarmas (yuqoridagi modul izohiga qarang)."""
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    phone_number: Optional[str] = Field(default=None, max_length=32)
    is_active: Optional[bool] = None


class RedeemedCustomerOut(BaseModel):
    customer_id: int
    full_name: str
    phone_number: Optional[str] = None
    promo_code: str
    redeemed_at: datetime
    bonus_window_ends_at: datetime


# ---------------------- Helpers ----------------------

def _out(s) -> PromoterOut:
    return PromoterOut(
        id=s.id,
        full_name=s.full_name,
        phone_number=s.phone_number,
        promo_code=s.promo_code,
        is_active=s.is_active,
        is_archived=s.is_archived,
        created_at=s.created_at,
        customers=s.customers,
        delivered_orders=s.delivered_orders,
        bonus_total=s.bonus_total,
    )


# ---------------------- Endpoints ----------------------

@router.get("", response_model=Page[PromoterOut])
async def list_promoters(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_archived: bool = Query(False),
    _=Depends(admin_required),
    promoters: PromoterService = Depends(get_promoter_service),
) -> Page[PromoterOut]:
    items, total = await promoters.list_with_stats(
        limit=limit, offset=offset, include_archived=include_archived,
    )
    return Page[PromoterOut](
        items=[_out(s) for s in items], total=total, limit=limit, offset=offset,
    )


@router.post("", response_model=PromoterOut, status_code=201)
async def create_promoter(
    payload: PromoterCreateIn,
    _=Depends(admin_required),
    promoters: PromoterService = Depends(get_promoter_service),
) -> PromoterOut:
    try:
        p = await promoters.create(
            full_name=payload.full_name,
            phone_number=payload.phone_number,
            promo_code=payload.promo_code,
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DomainError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Yangi promouterda statistika bo'lmaydi — 0 bilan qaytaramiz (qo'shimcha
    # so'rovlarsiz).
    return PromoterOut(
        id=p.id, full_name=p.full_name, phone_number=p.phone_number,
        promo_code=p.promo_code, is_active=bool(p.is_active), is_archived=False,
        created_at=p.created_at, customers=0, delivered_orders=0,
        bonus_total=Decimal("0.00"),
    )


@router.get("/{promoter_id}", response_model=PromoterOut)
async def get_promoter(
    promoter_id: int,
    _=Depends(admin_required),
    promoters: PromoterService = Depends(get_promoter_service),
) -> PromoterOut:
    try:
        return _out(await promoters.get_with_stats(promoter_id))
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Promouter topilmadi")


@router.patch("/{promoter_id}", response_model=PromoterOut)
async def update_promoter(
    promoter_id: int,
    payload: PromoterUpdateIn,
    _=Depends(admin_required),
    promoters: PromoterService = Depends(get_promoter_service),
) -> PromoterOut:
    try:
        await promoters.update(
            promoter_id,
            full_name=payload.full_name,
            phone_number=payload.phone_number,
            is_active=payload.is_active,
        )
        return _out(await promoters.get_with_stats(promoter_id))
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Promouter topilmadi")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DomainError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{promoter_id}", response_model=PromoterOut)
async def archive_promoter(
    promoter_id: int,
    _=Depends(admin_required),
    promoters: PromoterService = Depends(get_promoter_service),
) -> PromoterOut:
    """Arxivlash (soft delete) — ishdan ketgan ishchi.

    Qator DB'da QOLADI: eski zakazlarning `promoter_id` bog'lanishi va tarixiy
    KPI buzilmaydi. Kod endi o'tmaydi, yangi zakazlarga bonus yozilmaydi.
    """
    try:
        await promoters.archive(promoter_id)
        return _out(await promoters.get_with_stats(promoter_id))
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Promouter topilmadi")


@router.post("/{promoter_id}/restore", response_model=PromoterOut)
async def restore_promoter(
    promoter_id: int,
    _=Depends(admin_required),
    promoters: PromoterService = Depends(get_promoter_service),
) -> PromoterOut:
    try:
        await promoters.restore(promoter_id)
        return _out(await promoters.get_with_stats(promoter_id))
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Promouter topilmadi")


@router.get("/{promoter_id}/customers", response_model=Page[RedeemedCustomerOut])
async def list_promoter_customers(
    promoter_id: int,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _=Depends(admin_required),
    promoters: PromoterService = Depends(get_promoter_service),
) -> Page[RedeemedCustomerOut]:
    try:
        rows, total = await promoters.list_customers(
            promoter_id, limit=limit, offset=offset,
        )
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Promouter topilmadi")
    return Page[RedeemedCustomerOut](
        items=[
            RedeemedCustomerOut(
                customer_id=r.customer_id,
                full_name=r.customer.full_name if r.customer else "—",
                phone_number=r.customer.phone_number if r.customer else None,
                promo_code=r.promo_code,
                redeemed_at=r.created_at,
                bonus_window_ends_at=r.bonus_window_ends_at,
            )
            for r in rows
        ],
        total=total, limit=limit, offset=offset,
    )
