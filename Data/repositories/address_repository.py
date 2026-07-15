from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import func, select, update

from Data.repositories.base import BaseRepository
from Domain.models.address import CustomerAddress


class AddressRepository(BaseRepository[CustomerAddress]):
    model = CustomerAddress

    async def list_for_customer(self, customer_id: int) -> Sequence[CustomerAddress]:
        res = await self._session.execute(
            select(CustomerAddress)
            .where(CustomerAddress.customer_id == customer_id)
            .order_by(CustomerAddress.is_default.desc(), CustomerAddress.id.asc())
        )
        return res.scalars().all()

    async def get_for_customer(self, customer_id: int, address_id: int) -> Optional[CustomerAddress]:
        res = await self._session.execute(
            select(CustomerAddress).where(
                CustomerAddress.id == address_id,
                CustomerAddress.customer_id == customer_id,
            )
        )
        return res.scalar_one_or_none()

    async def get_by_label(self, customer_id: int, label: str) -> Optional[CustomerAddress]:
        res = await self._session.execute(
            select(CustomerAddress).where(
                CustomerAddress.customer_id == customer_id,
                CustomerAddress.label == label,
            )
        )
        return res.scalar_one_or_none()

    async def count_for_customer(self, customer_id: int) -> int:
        res = await self._session.execute(
            select(func.count(CustomerAddress.id)).where(
                CustomerAddress.customer_id == customer_id
            )
        )
        return int(res.scalar_one() or 0)

    async def clear_default(self, customer_id: int) -> None:
        """Mijozning barcha manzillarini is_default=False qiladi.

        Yangi default tayinlashdan oldin chaqiriladi — bitta default qoladi.
        """
        await self._session.execute(
            update(CustomerAddress)
            .where(CustomerAddress.customer_id == customer_id, CustomerAddress.is_default.is_(True))
            .values(is_default=False)
        )
