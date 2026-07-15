"""Savatcha endpointlari — bot va WebApp uchun yagona manba."""
from __future__ import annotations

from dataclasses import asdict
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from Domain.constants import MAX_QUANTITY_PER_ITEM
from Service.cart_service import CartService
from Service.exceptions import DomainError, InvalidOperationError, ValidationError
from webapp.auth import TelegramUser
from webapp.deps import get_cart_service, telegram_user

router = APIRouter(prefix="/api/cart", tags=["cart"])


class CartLineOut(BaseModel):
    food_id: int
    name: str
    price: float
    quantity: int
    image_path: str | None = None
    line_total: float


class CartViewOut(BaseModel):
    items: List[CartLineOut]
    total: float
    count: int


class SetItemIn(BaseModel):
    food_id: int = Field(gt=0)
    quantity: int = Field(ge=0, le=MAX_QUANTITY_PER_ITEM)


def _to_view_out(view) -> CartViewOut:
    # CartLine `slots=True` bilan — `__dict__` yo'q. `asdict()` xavfsiz va to'g'ri.
    return CartViewOut(
        items=[CartLineOut(**asdict(i)) for i in view.items],
        total=view.total,
        count=view.count,
    )


@router.get("", response_model=CartViewOut)
async def get_cart(
    user: TelegramUser = Depends(telegram_user),
    carts: CartService = Depends(get_cart_service),
) -> CartViewOut:
    view = await carts.view(user.id)
    return _to_view_out(view)


@router.post("/items", response_model=CartViewOut)
async def set_item(
    payload: SetItemIn,
    user: TelegramUser = Depends(telegram_user),
    carts: CartService = Depends(get_cart_service),
) -> CartViewOut:
    try:
        view = await carts.set_quantity(user.id, payload.food_id, payload.quantity)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidOperationError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except DomainError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_view_out(view)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, response_class=None)
async def clear_cart(
    user: TelegramUser = Depends(telegram_user),
    carts: CartService = Depends(get_cart_service),
):
    from fastapi.responses import Response
    await carts.clear(user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
