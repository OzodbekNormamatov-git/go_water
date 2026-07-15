"""Mijozning saqlangan manzillari — Address Book CRUD."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from Service.address_service import AddressInput, AddressService
from Service.exceptions import (
    DomainError,
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from webapp.auth import TelegramUser
from webapp.deps import get_address_service, telegram_user
from webapp.schemas import AddressIn, AddressOut

router = APIRouter(prefix="/api/me/addresses", tags=["me:addresses"])


def _to_out(a) -> AddressOut:
    return AddressOut(
        id=a.id,
        label=a.label,
        latitude=float(a.latitude),
        longitude=float(a.longitude),
        details=a.details or "",
        is_default=bool(a.is_default),
    )


def _to_input(payload: AddressIn) -> AddressInput:
    return AddressInput(
        label=payload.label,
        latitude=float(payload.latitude),
        longitude=float(payload.longitude),
        details=payload.details,
        is_default=bool(payload.is_default),
    )


@router.get("", response_model=List[AddressOut])
async def list_addresses(
    user: TelegramUser = Depends(telegram_user),
    addresses: AddressService = Depends(get_address_service),
) -> List[AddressOut]:
    items = await addresses.list_for_user(user.id)
    return [_to_out(a) for a in items]


@router.post("", response_model=AddressOut, status_code=status.HTTP_201_CREATED)
async def create_address(
    payload: AddressIn,
    user: TelegramUser = Depends(telegram_user),
    addresses: AddressService = Depends(get_address_service),
) -> AddressOut:
    try:
        addr = await addresses.create(user.id, _to_input(payload))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidOperationError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except DomainError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_out(addr)


@router.patch("/{address_id}", response_model=AddressOut)
async def update_address(
    address_id: int,
    payload: AddressIn,
    user: TelegramUser = Depends(telegram_user),
    addresses: AddressService = Depends(get_address_service),
) -> AddressOut:
    try:
        addr = await addresses.update(user.id, address_id, _to_input(payload))
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Manzil topilmadi.")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidOperationError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _to_out(addr)


@router.post("/{address_id}/default", response_model=AddressOut)
async def make_default(
    address_id: int,
    user: TelegramUser = Depends(telegram_user),
    addresses: AddressService = Depends(get_address_service),
) -> AddressOut:
    try:
        addr = await addresses.set_default(user.id, address_id)
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Manzil topilmadi.")
    except InvalidOperationError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _to_out(addr)


@router.delete("/{address_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=None)
async def delete_address(
    address_id: int,
    user: TelegramUser = Depends(telegram_user),
    addresses: AddressService = Depends(get_address_service),
):
    from fastapi.responses import Response
    try:
        await addresses.delete(user.id, address_id)
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Manzil topilmadi.")
    except InvalidOperationError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
