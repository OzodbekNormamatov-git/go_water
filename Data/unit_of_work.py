from __future__ import annotations

from types import TracebackType
from typing import Optional, Type

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from Data.repositories.address_repository import AddressRepository
from Data.repositories.broadcast_repository import BroadcastRepository
from Data.repositories.cart_repository import CartRepository
from Data.repositories.courier_repository import CourierRepository
from Data.repositories.expense_repository import ExpenseRepository
from Data.repositories.food_repository import FoodRepository
from Data.repositories.ledger_repository import LedgerRepository
from Data.repositories.operator_call_repository import OperatorCallRepository
from Data.repositories.operator_repository import OperatorRepository
from Data.repositories.order_repository import OrderRepository
from Data.repositories.promoter_repository import (
    PromoterRedemptionRepository,
    PromoterRepository,
)
from Data.repositories.reminder_repository import ReminderRepository
from Data.repositories.settings_repository import SettingsRepository
from Data.repositories.user_repository import UserRepository


class UnitOfWork:
    """
    Bitta atomic operatsiya doirasida bir nechta repolarni birlashtiradi.
    `async with uow:` blokidan tashqarida sodir bo'lgan exception'da rollback qiladi.
    """

    users: UserRepository
    couriers: CourierRepository
    foods: FoodRepository
    orders: OrderRepository
    carts: CartRepository
    addresses: AddressRepository
    broadcasts: BroadcastRepository
    settings: SettingsRepository
    ledger: LedgerRepository
    reminders: ReminderRepository
    expenses: ExpenseRepository
    operator_calls: OperatorCallRepository
    operators: OperatorRepository
    promoters: PromoterRepository
    promoter_redemptions: PromoterRedemptionRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: Optional[AsyncSession] = None

    async def __aenter__(self) -> "UnitOfWork":
        self._session = self._session_factory()
        self.users = UserRepository(self._session)
        self.couriers = CourierRepository(self._session)
        self.foods = FoodRepository(self._session)
        self.orders = OrderRepository(self._session)
        self.carts = CartRepository(self._session)
        self.addresses = AddressRepository(self._session)
        self.broadcasts = BroadcastRepository(self._session)
        self.settings = SettingsRepository(self._session)
        self.ledger = LedgerRepository(self._session)
        self.reminders = ReminderRepository(self._session)
        self.expenses = ExpenseRepository(self._session)
        self.operator_calls = OperatorCallRepository(self._session)
        self.operators = OperatorRepository(self._session)
        self.promoters = PromoterRepository(self._session)
        self.promoter_redemptions = PromoterRedemptionRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        assert self._session is not None
        try:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork session faqat `async with` ichida ishlaydi")
        return self._session

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
