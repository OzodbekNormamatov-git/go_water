"""Manzillar xotirasi (Address Book) — mijozning saqlangan manzillari.

Mijoz har safar lat/lon yozmasdan, "Uy"/"Ish" kabi yorliqli manzilini
bir bosishda tanlay oladi. CRUD + default belgilash.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from Data.unit_of_work import UnitOfWork
from Domain.constants import (
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
    MAX_ADDRESSES_PER_USER,
    MAX_ADDRESS_DETAILS_LENGTH,
    MAX_ADDRESS_LABEL_LENGTH,
)
from Domain.models.address import CustomerAddress
from Service.exceptions import (
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)


@dataclass(slots=True)
class AddressInput:
    label: str
    latitude: float
    longitude: float
    details: str = ""
    is_default: bool = False


def _validate(data: AddressInput) -> None:
    label = (data.label or "").strip()
    if not label:
        raise ValidationError("address_label_required")
    if len(label) > MAX_ADDRESS_LABEL_LENGTH:
        raise ValidationError(
            "address_label_too_long", context={"max": MAX_ADDRESS_LABEL_LENGTH},
        )
    details = (data.details or "").strip()
    if len(details) > MAX_ADDRESS_DETAILS_LENGTH:
        raise ValidationError(
            "address_details_too_long", context={"max": MAX_ADDRESS_DETAILS_LENGTH},
        )
    if not (LAT_MIN <= float(data.latitude) <= LAT_MAX) or not (
        LON_MIN <= float(data.longitude) <= LON_MAX
    ):
        raise ValidationError("location_invalid")


class AddressService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def list_for_user(self, telegram_id: int) -> Sequence[CustomerAddress]:
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get_by_telegram_id(telegram_id)
            if user is None:
                return []
            return await uow.addresses.list_for_customer(user.id)

    async def get(self, telegram_id: int, address_id: int) -> CustomerAddress:
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get_by_telegram_id(telegram_id)
            if user is None:
                raise InvalidOperationError("user_not_registered")
            addr = await uow.addresses.get_for_customer(user.id, address_id)
            if addr is None:
                raise EntityNotFoundError("address_not_found")
            return addr

    async def create(self, telegram_id: int, data: AddressInput) -> CustomerAddress:
        _validate(data)
        label = data.label.strip()
        details = (data.details or "").strip()
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get_by_telegram_id(telegram_id)
            if user is None:
                raise InvalidOperationError("user_not_registered")

            count = await uow.addresses.count_for_customer(user.id)
            if count >= MAX_ADDRESSES_PER_USER:
                raise ValidationError(
                    "address_limit_reached", context={"max": MAX_ADDRESSES_PER_USER},
                )
            taken = await uow.addresses.get_by_label(user.id, label)
            if taken is not None:
                raise ValidationError("address_label_taken")

            make_default = bool(data.is_default) or count == 0
            if make_default:
                await uow.addresses.clear_default(user.id)

            addr = CustomerAddress(
                customer_id=user.id,
                label=label,
                details=details,
                latitude=float(data.latitude),
                longitude=float(data.longitude),
                is_default=make_default,
            )
            return await uow.addresses.add(addr)

    async def update(
        self,
        telegram_id: int,
        address_id: int,
        data: AddressInput,
    ) -> CustomerAddress:
        _validate(data)
        label = data.label.strip()
        details = (data.details or "").strip()
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get_by_telegram_id(telegram_id)
            if user is None:
                raise InvalidOperationError("user_not_registered")
            addr = await uow.addresses.get_for_customer(user.id, address_id)
            if addr is None:
                raise EntityNotFoundError("address_not_found")

            if label != addr.label:
                taken = await uow.addresses.get_by_label(user.id, label)
                if taken is not None:
                    raise ValidationError("address_label_taken")
            addr.label = label
            addr.details = details
            addr.latitude = float(data.latitude)
            addr.longitude = float(data.longitude)

            if bool(data.is_default) and not addr.is_default:
                await uow.addresses.clear_default(user.id)
                addr.is_default = True
            elif not bool(data.is_default) and addr.is_default:
                # Bitta default qoladi — agar default'ni olib tashlasa, hech
                # qanday yangi default tayinlamaymiz (caller hohlasa keyin tanlaydi).
                addr.is_default = False
            await uow.addresses.add(addr)
            return addr

    async def delete(self, telegram_id: int, address_id: int) -> None:
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get_by_telegram_id(telegram_id)
            if user is None:
                raise InvalidOperationError("user_not_registered")
            addr = await uow.addresses.get_for_customer(user.id, address_id)
            if addr is None:
                raise EntityNotFoundError("address_not_found")
            was_default = addr.is_default
            await uow.addresses.delete(addr)
            # O'chirilgan default o'rniga eng birinchisini default qilamiz.
            if was_default:
                remaining = await uow.addresses.list_for_customer(user.id)
                if remaining:
                    first = remaining[0]
                    first.is_default = True
                    await uow.addresses.add(first)

    async def set_default(self, telegram_id: int, address_id: int) -> CustomerAddress:
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get_by_telegram_id(telegram_id)
            if user is None:
                raise InvalidOperationError("user_not_registered")
            addr = await uow.addresses.get_for_customer(user.id, address_id)
            if addr is None:
                raise EntityNotFoundError("address_not_found")
            await uow.addresses.clear_default(user.id)
            addr.is_default = True
            await uow.addresses.add(addr)
            return addr
