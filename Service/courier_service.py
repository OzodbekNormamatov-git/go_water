from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from Data.unit_of_work import UnitOfWork
from Domain.models.courier import Courier
from Domain.models.ledger import LedgerAccount, LedgerKind
from Service.exceptions import (
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from Service.ledger_posting import post_ledger
from Service.phone import normalize_phone


def _normalize_phone(raw: Optional[str]) -> Optional[str]:
    """Kuryer telefoni: None/bo'sh → None (nullable), aks holda umumiy
    +998-normalizatsiya (Service/phone.py — yagona manba)."""
    if raw is None or not str(raw).strip():
        return None
    return normalize_phone(raw)


class CourierService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_or_register(
        self,
        telegram_id: int,
        full_name: str,
        username: Optional[str] = None,
        *,
        mark_started: bool = False,
    ) -> Courier:
        """
        DM /start: yangi kuryer yaratiladi (default: is_active=False, has_started_bot=mark_started).
        Mavjud kuryerda — ism/username sinxron qilinadi va kerak bo'lsa has_started_bot=True qilinadi.
        is_active'ga bu yerda HECH QACHON tegmaymiz — uni faqat admin o'zgartiradi.
        """
        async with UnitOfWork(self._sf) as uow:
            courier = await uow.couriers.get_by_telegram_id(telegram_id)
            if courier is None:
                courier = Courier(
                    telegram_id=telegram_id,
                    full_name=full_name or f"Kuryer #{telegram_id}",
                    username=username,
                    is_active=False,
                    has_started_bot=mark_started,
                )
                await uow.couriers.add(courier)
            else:
                # Arxivlangan kuryer qaytadan /start yuborsa — meta-ma'lumotni
                # yangilamaymiz va is_active hech qachon o'z-o'zidan True bo'lmaydi
                # (admin qo'lda arxivdan qaytarib, keyin yoqishi kerak).
                if courier.is_deleted:
                    return courier
                changed = False
                if full_name and courier.full_name != full_name:
                    courier.full_name = full_name
                    changed = True
                if username and courier.username != username:
                    courier.username = username
                    changed = True
                if mark_started and not courier.has_started_bot:
                    courier.has_started_bot = True
                    changed = True
                if changed:
                    await uow.couriers.add(courier)
            return courier

    async def mark_bot_unreachable(self, telegram_id: int) -> None:
        """DM yuborilmaganda (Forbidden) — keyingi claim'gacha qayta /start talab qilamiz."""
        async with UnitOfWork(self._sf) as uow:
            courier = await uow.couriers.get_by_telegram_id(telegram_id)
            if courier is None:
                return
            if courier.has_started_bot:
                courier.has_started_bot = False
                await uow.couriers.add(courier)

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[Courier]:
        async with UnitOfWork(self._sf) as uow:
            return await uow.couriers.get_by_telegram_id(telegram_id)

    async def list_all(self) -> Sequence[Courier]:
        async with UnitOfWork(self._sf) as uow:
            return await uow.couriers.list_all_ordered()

    async def list_paginated(
        self, *, archived: bool = False, limit: int = 50, offset: int = 0,
    ) -> tuple[Sequence[Courier], int]:
        """Admin uchun: paginatsiyalangan ro'yxat + total."""
        async with UnitOfWork(self._sf) as uow:
            total = await uow.couriers.count(archived=archived)
            items = await uow.couriers.list_paginated(
                archived=archived, limit=limit, offset=offset,
            )
            return items, total

    async def get(self, courier_id: int) -> Courier:
        async with UnitOfWork(self._sf) as uow:
            courier = await uow.couriers.get(courier_id)
            if courier is None:
                raise EntityNotFoundError("courier_not_registered")
            return courier

    async def set_active(self, courier_id: int, active: bool) -> Courier:
        async with UnitOfWork(self._sf) as uow:
            courier = await uow.couriers.get(courier_id)
            if courier is None:
                raise EntityNotFoundError("courier_not_registered")
            courier.is_active = active
            await uow.couriers.add(courier)
            return courier

    # ---------------------- Naqd pul (cash) ----------------------

    async def settle_cash(
        self, courier_id: int, amount: Optional[Decimal] = None,
        *, operator_id: int | None = None,
    ) -> Courier:
        """Kuryer naqd pulni topshirdi — balansidan ayiramiz (admin "qabul qildim").

        `amount=None` → to'liq balansni nolga tushiradi (hammasini topshirdi).
        `amount` berilsa → shu summani ayiradi (qisman topshirish), balansdan oshmaydi.

        Xatolar:
          * EntityNotFound — kuryer yo'q
          * ValidationError("cash_amount_invalid") — manfiy/noto'g'ri summa
          * InvalidOperationError("cash_settle_exceeds") — balansdan ko'p
        """
        async with UnitOfWork(self._sf) as uow:
            courier = await uow.couriers.get_for_update(courier_id)
            if courier is None:
                raise EntityNotFoundError("courier_not_registered")
            balance = Decimal(courier.cash_balance or 0)
            if amount is None:
                take = balance  # hammasini topshirdi
            else:
                try:
                    take = Decimal(str(amount))
                except (InvalidOperation, TypeError, ValueError):
                    raise ValidationError("cash_amount_invalid")
                if take <= 0:
                    raise ValidationError("cash_amount_invalid")
                if take > balance:
                    raise InvalidOperationError(
                        "cash_settle_exceeds",
                        context={"available": float(balance)},
                    )
            # Naqd 0 bo'lsa (topshiradigan narsa yo'q) — yozuv qoldirmaymiz.
            if take > 0:
                await post_ledger(
                    uow, subject=courier,
                    account=LedgerAccount.CASH, kind=LedgerKind.CASH_SETTLE,
                    delta=-take, operator_id=operator_id,
                    reason="Kuryer naqd pulni topshirdi (admin qabul qildi)",
                )
            return courier

    async def total_cash_outstanding(self) -> tuple[float, int]:
        """Barcha kuryerlar qo'lidagi jami naqd + naqdi bor kuryerlar soni."""
        async with UnitOfWork(self._sf) as uow:
            return await uow.couriers.total_cash_outstanding()

    async def set_phone(self, courier_id: int, phone: Optional[str]) -> Courier:
        """Kuryer telefon raqamini yangilaydi (admin tomondan yoki kuryerning o'zi).

        `phone=None` yoki bo'sh string — telefonni tozalaydi. Aks holda
        E.164 ga normalize qilinadi. Noto'g'ri format `ValidationError("phone_invalid")`.
        """
        normalized = _normalize_phone(phone)
        async with UnitOfWork(self._sf) as uow:
            courier = await uow.couriers.get(courier_id)
            if courier is None:
                raise EntityNotFoundError("courier_not_registered")
            courier.phone_number = normalized
            await uow.couriers.add(courier)
            return courier

    async def set_phone_by_telegram_id(
        self, telegram_id: int, phone: Optional[str],
    ) -> Optional[Courier]:
        """Kuryer botida /start qilganda — telefonini saqlash uchun.

        Kuryer ro'yxatdan o'tmagan bo'lsa `None` qaytaradi (silent, chunki kuryer
        avval `get_or_register` ga keladi). Phone validatsiya yo'q (bot
        `request_contact=True` orqali Telegram berib turibdi — ishonchli manba).
        """
        # Telegram contact'dan kelgan raqam doim valid bo'lishi kerak, lekin
        # baribir normalize qilamiz (boshqa kanal'lardan kelishi mumkin).
        normalized = _normalize_phone(phone)
        async with UnitOfWork(self._sf) as uow:
            courier = await uow.couriers.get_by_telegram_id(telegram_id)
            if courier is None:
                return None
            if courier.phone_number == normalized:
                return courier
            courier.phone_number = normalized
            await uow.couriers.add(courier)
            return courier

    async def archive(self, courier_id: int) -> None:
        """SOFT DELETE — kuryerni arxivlash (ishdan ketgan kuryer uchun).

        Eski buyurtmalarda ko'rinishi saqlanadi. Admin "Arxiv" tab'idan
        `restore()` orqali qaytarish mumkin. Idempotent.
        """
        async with UnitOfWork(self._sf) as uow:
            courier = await uow.couriers.get(courier_id)
            if courier is None or courier.is_deleted:
                return
            # Arxivlangan kuryer endi aktiv emas (yangi claim olmasin)
            courier.is_active = False
            await uow.couriers.soft_delete(courier)

    async def restore(self, courier_id: int) -> Courier:
        """Arxivlangan kuryerni qaytaradi (deleted_at = NULL). is_active=False qoladi —
        admin ehtiyot bo'lib qo'lda yoqishi kerak."""
        async with UnitOfWork(self._sf) as uow:
            courier = await uow.couriers.get(courier_id)
            if courier is None:
                raise EntityNotFoundError("courier_not_registered")
            if not courier.is_deleted:
                return courier
            return await uow.couriers.restore(courier)
