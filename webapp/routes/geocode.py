"""Geocoding — manzil qidiruv + teskari geocoding (proxy, OSM/Photon).

Backend orqali o'tkazamiz: kalit (kelajakda self-host bo'lsa) frontga chiqmaydi,
keshlash markazlashgan, ikkala Mini App ham (mijoz + admin) ishlatadi.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from Service.geocode_service import GeocodeService
from webapp.auth import TelegramUser
from webapp.deps import any_telegram_user, get_geocode_service

router = APIRouter(prefix="/api", tags=["geocode"])


class GeocodeHit(BaseModel):
    title: str
    subtitle: str = ""
    address: str = ""
    latitude: float
    longitude: float


class ReverseOut(BaseModel):
    address: str = ""


@router.get("/geocode", response_model=List[GeocodeHit])
async def geocode(
    q: str = Query(min_length=2, max_length=120),
    lat: Optional[float] = Query(default=None),
    lon: Optional[float] = Query(default=None),
    _user: TelegramUser = Depends(any_telegram_user),
    geo: GeocodeService = Depends(get_geocode_service),
) -> List[GeocodeHit]:
    """Manzil/ko'cha/mahalla qidirish (avtocomplete). Hudud lat/lon bilan moyil."""
    rows = await geo.search(q, lat=lat, lon=lon, limit=6)
    return [GeocodeHit(**r) for r in rows]


@router.get("/reverse-geocode", response_model=ReverseOut)
async def reverse_geocode(
    lat: float = Query(...),
    lon: float = Query(...),
    _user: TelegramUser = Depends(any_telegram_user),
    geo: GeocodeService = Depends(get_geocode_service),
) -> ReverseOut:
    """x,y -> o'qiladigan manzil (ko'cha/uy/mahalla)."""
    return ReverseOut(address=await geo.reverse(lat, lon))
