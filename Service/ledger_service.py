"""LedgerService — mijozning keshbek va idishlar (bottle) balansini boshqarish.

* **cashback_balance** — Decimal (so'mda), DELIVERED bo'lganda buyurtma
  `cashback_earned` qatori bilan ortadi; mijoz keyingi buyurtmada
  `cashback_used` orqali ishlatadi.
* **bottles_balance** — Integer, DELIVERED bo'lganda
  `bottles_issued − bottles_returned` qadar yangilanadi.

Cashback math sof funksiyalar (`compute_cashback_for`, `cap_cashback_usage`)
admin sozlamalari (percent, max_usage_ratio) bilan parametrlanadi — `OrderService`
har orderda live config'ni `AppSettings`'dan o'qib uzatadi.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from Data.unit_of_work import UnitOfWork
from Domain.constants import (
    CASHBACK_ROUND_UNIT,
    CASHBACK_USE_UNIT,
    DEFAULT_CASHBACK_PERCENT,
    DEFAULT_MAX_CASHBACK_USAGE_RATIO,
    MAX_BOTTLES_PER_TRANSACTION,
)
from Domain.models.ledger import LedgerAccount, LedgerKind
from Domain.models.user import User
from Service.exceptions import (
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from Service.ledger_posting import post_ledger


@dataclass(slots=True)
class BalanceView:
    cashback_balance: Decimal
    bottles_balance: int
    # Cashback dasturi konfiguratsiyasi — UI checkout'da sliderni ko'rsatish/yashirish uchun.
    cashback_enabled: bool
    cashback_percent: float
    max_cashback_usage_ratio: float
    # Mijoz UI uchun — slider step va minimum
    cashback_use_unit: int = CASHBACK_USE_UNIT
    # Oldindan to'lov (avans/depozit) balansi — checkout "Balansdan" opsiyasi uchun.
    deposit_balance: Decimal = Decimal("0.00")


def quantize_cashback(amount: Decimal | float | int) -> Decimal:
    """Cashback EARN qadami (100 so'm) bo'yicha FLOOR.

    Mijoz QO'LGA OLAYOTGAN keshbek shu birlikga moslanadi.
    Misol: 47.12 → 0; 708.45 → 700; 2547.99 → 2500.
    """
    return _floor_to_unit(amount, CASHBACK_ROUND_UNIT)


def quantize_cashback_use(amount: Decimal | float | int) -> Decimal:
    """Cashback PAYMENT qadami (1000 so'm) bo'yicha FLOOR.

    Buyurtmada qoplashda ishlatiladi. 1400 → 1000; 5700 → 5000.
    """
    return _floor_to_unit(amount, CASHBACK_USE_UNIT)


def _floor_to_unit(amount: Decimal | float | int, unit_value: int) -> Decimal:
    if amount is None:
        return Decimal("0.00")
    dec = Decimal(str(amount))
    if dec <= 0:
        return Decimal("0.00")
    unit = Decimal(unit_value)
    floored = (dec // unit) * unit
    return floored.quantize(Decimal("0.01"))


def compute_cashback_for(items_total: Decimal, percent: Decimal | float) -> Decimal:
    """Sotuv summasidan keshbek miqdorini hisoblaydi.

    `percent` faol konfiguratsiyadan keladi (dinamik). Ishlatuvchi caller
    cashback_enabled tekshiruvini o'zi qiladi.
    """
    p = Decimal(str(percent))
    if p <= 0:
        return Decimal("0.00")
    raw = Decimal(str(items_total)) * p / Decimal("100")
    return quantize_cashback(raw)


def cap_cashback_usage(
    items_total: Decimal,
    requested: Decimal,
    max_usage_ratio: Decimal | float,
) -> Decimal:
    """Bitta buyurtmada keshbek bilan qoplashning chegarasini qo'llaydi.

    Qadam — `CASHBACK_USE_UNIT` (1000 so'm). 1400 yuborilsa 1000 qaytadi.
    Ulush chegarasi (`max_usage_ratio`) ham qoplanadi: 0.5 = 50%, 1.0 = to'liq.
    """
    requested = Decimal(str(requested or 0))
    if requested <= 0:
        return Decimal("0.00")
    ratio = Decimal(str(max_usage_ratio))
    if ratio <= 0:
        return Decimal("0.00")
    cap = Decimal(str(items_total)) * ratio
    cap_q = quantize_cashback_use(cap)
    # USE-unit'ga FLOOR — mijozga ko'rsatilgan slider step bilan moslashadi
    capped = min(requested, cap_q)
    return quantize_cashback_use(capped)


class LedgerService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_balance(self, telegram_id: int) -> BalanceView:
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get_by_telegram_id(telegram_id)
            cfg = await uow.settings.get_or_create()
            cashback = Decimal(user.cashback_balance or 0) if user else Decimal("0.00")
            bottles = int(user.bottles_balance or 0) if user else 0
            deposit = Decimal(getattr(user, "deposit_balance", 0) or 0) if user else Decimal("0.00")
            return BalanceView(
                cashback_balance=cashback,
                bottles_balance=bottles,
                deposit_balance=deposit,
                cashback_enabled=bool(cfg.cashback_enabled),
                cashback_percent=float(cfg.cashback_percent or DEFAULT_CASHBACK_PERCENT),
                max_cashback_usage_ratio=float(
                    cfg.max_cashback_usage_ratio or DEFAULT_MAX_CASHBACK_USAGE_RATIO
                ),
                cashback_use_unit=CASHBACK_USE_UNIT,
            )

    # ---------------------- Jurnal o'qish / tekshirish ----------------------

    async def history(
        self,
        subject_type: str,
        subject_id: int,
        *,
        account: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        """Subyekt hisobining jurnal tarixi + umumiy son (paginatsiya uchun)."""
        async with UnitOfWork(self._sf) as uow:
            total = await uow.ledger.count_for_subject(
                subject_type, subject_id, account=account,
            )
            entries = await uow.ledger.list_for_subject(
                subject_type, subject_id, account=account, limit=limit, offset=offset,
            )
            return entries, total

    async def verify_balance(
        self, subject_type: str, subject_id: int, account: str,
    ) -> tuple[Decimal, Decimal, bool]:
        """Kesh balansni jurnal yig'indisi bilan solishtiradi (yaxlitlik tekshiruvi).

        Qaytaradi: (jurnal_summasi, kesh_balansi, mos_keladimi).
        Mos kelmasa — bug yoki qo'lda DB tahriri bo'lgan (audit signal).
        """
        async with UnitOfWork(self._sf) as uow:
            computed = await uow.ledger.computed_balance(subject_type, subject_id, account)
            if subject_type == "courier":
                subj = await uow.couriers.get(subject_id)
                cached = Decimal(subj.cash_balance or 0) if subj else Decimal("0")
            else:
                subj = await uow.users.get(subject_id)
                if subj is None:
                    cached = Decimal("0")
                elif account == "bottles":
                    cached = Decimal(int(subj.bottles_balance or 0))
                else:
                    cached = Decimal(subj.cashback_balance or 0)
            return computed, cached, computed == cached

    # ---------------------- Admin manual adjustment ----------------------

    async def adjust_cashback(
        self, user_id: int, delta: Decimal, *, reason: str = "", operator_id: int | None = None,
    ) -> User:
        if delta is None:
            raise ValidationError("cashback_negative")
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get_for_update(user_id)
            if user is None:
                raise EntityNotFoundError("user_not_registered")
            # Spetsifik UX xatosi uchun oldindan tekshirish (post_ledger generic
            # "balance_negative" beradi; bu yerda aniqroq xabar chiqaramiz).
            if Decimal(user.cashback_balance or 0) + Decimal(str(delta)) < 0:
                raise InvalidOperationError(
                    "cashback_not_enough",
                    context={"available": float(user.cashback_balance or 0)},
                )
            await post_ledger(
                uow, subject=user,
                account=LedgerAccount.CASHBACK, kind=LedgerKind.CASHBACK_ADJUST,
                delta=Decimal(str(delta)), operator_id=operator_id,
                reason=reason or "Admin qo'lda tuzatishi",
            )
            return user

    async def adjust_deposit(
        self, user_id: int, delta: Decimal, *, reason: str = "", operator_id: int | None = None,
    ) -> User:
        """Depozit (avans) balansini qo'lda o'zgartirish — admin.

        Musbat delta = mijoz pul o'tkazdi (DEPOSIT_TOPUP);
        manfiy delta = tuzatish/qaytarish (DEPOSIT_ADJUST).
        Balans manfiy bo'lib qola olmaydi (DB CHECK + post_ledger himoyasi).
        """
        if delta is None:
            raise ValidationError("deposit_delta_invalid")
        delta_d = Decimal(str(delta))
        if delta_d == 0:
            raise ValidationError("deposit_delta_invalid")
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get_for_update(user_id)
            if user is None:
                raise EntityNotFoundError("user_not_registered")
            if Decimal(user.deposit_balance or 0) + delta_d < 0:
                raise InvalidOperationError(
                    "deposit_not_enough",
                    context={"available": float(user.deposit_balance or 0)},
                )
            kind = LedgerKind.DEPOSIT_TOPUP if delta_d > 0 else LedgerKind.DEPOSIT_ADJUST
            await post_ledger(
                uow, subject=user,
                account=LedgerAccount.DEPOSIT, kind=kind,
                delta=delta_d, operator_id=operator_id,
                reason=reason or ("Balans to'ldirildi" if delta_d > 0 else "Admin qo'lda tuzatishi"),
            )
            return user

    async def adjust_bottles(
        self, user_id: int, delta: int, *, reason: str = "", operator_id: int | None = None,
    ) -> User:
        if delta is None:
            raise ValidationError(
                "bottles_out_of_range", context={"max": MAX_BOTTLES_PER_TRANSACTION},
            )
        try:
            delta_int = int(delta)
        except (TypeError, ValueError):
            raise ValidationError(
                "bottles_out_of_range", context={"max": MAX_BOTTLES_PER_TRANSACTION},
            )
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get_for_update(user_id)
            if user is None:
                raise EntityNotFoundError("user_not_registered")
            if int(user.bottles_balance or 0) + delta_int < 0:
                raise InvalidOperationError(
                    "bottles_return_exceeds_balance",
                    context={
                        "available": int(user.bottles_balance or 0),
                        "requested": abs(delta_int),
                    },
                )
            await post_ledger(
                uow, subject=user,
                account=LedgerAccount.BOTTLES, kind=LedgerKind.BOTTLE_ADJUST,
                delta=delta_int, operator_id=operator_id,
                reason=reason or "Admin qo'lda tuzatishi",
            )
            return user
