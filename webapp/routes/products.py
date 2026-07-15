"""Mahsulotlar — public endpoint'lar.

Mahsulotlar ro'yxati kim ko'rishidan qat'i nazar bir xil; biroq
Telegram'dan kelganini tasdiqlash uchun baribir auth'ni talab qilamiz —
shu orqali web botni "open API" bo'lib chiqib ketishidan saqlaymiz.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from Service.exceptions import EntityNotFoundError
from Service.food_service import FoodService
from webapp.auth import TelegramUser
from webapp.deps import get_food_service, telegram_user
from webapp.schemas import ProductOut

router = APIRouter(prefix="/api/products", tags=["products"])


def _image_url(request: Request, image_value: Optional[str]) -> Optional[str]:
    """`Food.image_file_id` (disk path nisbiy) -> URL.

    Eski yozuvlarda bu Telegram file_id bo'lishi mumkin (cross-bot ishlamaydi
    va URL ham emas) — bunday hollarda None qaytaramiz.
    """
    if not image_value:
        return None
    if image_value.startswith("media/"):
        return f"{request.base_url}{image_value}".rstrip("/")
    # noma'lum format — None
    return None


@router.get("", response_model=List[ProductOut])
async def list_products(
    request: Request,
    _user: TelegramUser = Depends(telegram_user),
    foods: FoodService = Depends(get_food_service),
) -> List[ProductOut]:
    items = await foods.list_menu()
    return [
        ProductOut(
            id=f.id,
            name=f.name,
            description=f.description or "",
            price=f.price,
            min_quantity=int(getattr(f, "min_quantity", 1) or 1),
            bottles_per_unit=int(getattr(f, "bottles_per_unit", 1) or 0),
            image_url=_image_url(request, f.image_file_id),
        )
        for f in items
    ]


@router.get("/{food_id}", response_model=ProductOut)
async def get_product(
    food_id: int,
    request: Request,
    _user: TelegramUser = Depends(telegram_user),
    foods: FoodService = Depends(get_food_service),
) -> ProductOut:
    try:
        f = await foods.get(food_id)
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mahsulot topilmadi.")
    return ProductOut(
        id=f.id,
        name=f.name,
        description=f.description or "",
        price=f.price,
        min_quantity=int(getattr(f, "min_quantity", 1) or 1),
        bottles_per_unit=int(getattr(f, "bottles_per_unit", 1) or 0),
        image_url=_image_url(request, f.image_file_id),
    )
