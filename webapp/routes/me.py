"""Joriy foydalanuvchi (me) — profil, balans va ro'yxatdan o'tish."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status

from Service.exceptions import ValidationError
from Service.ledger_service import LedgerService
from Service.user_service import RegistrationInput, UserService
from webapp.auth import TelegramUser
from webapp.deps import (
    get_brand_name,
    get_ledger_service,
    get_user_service,
    telegram_user,
)
from webapp.schemas import BalanceOut, MeOut, RegisterIn

router = APIRouter(prefix="/api/me", tags=["me"])


def _balance_or_zero(db_user) -> tuple[Decimal, int, Decimal]:
    if db_user is None:
        return Decimal("0.00"), 0, Decimal("0.00")
    return (
        Decimal(db_user.cashback_balance or 0),
        int(db_user.bottles_balance or 0),
        Decimal(getattr(db_user, "deposit_balance", 0) or 0),
    )


@router.get("", response_model=MeOut)
async def get_me(
    user: TelegramUser = Depends(telegram_user),
    users: UserService = Depends(get_user_service),
    brand_name: str = Depends(get_brand_name),
) -> MeOut:
    db_user = await users.get_by_telegram_id(user.id)
    cashback, bottles, deposit = _balance_or_zero(db_user)
    return MeOut(
        telegram_id=user.id,
        is_registered=db_user is not None,
        full_name=db_user.full_name if db_user else None,
        phone_number=db_user.phone_number if db_user else None,
        tg_first_name=user.first_name,
        tg_last_name=user.last_name,
        tg_username=user.username,
        brand_name=brand_name,
        cashback_balance=cashback,
        bottles_balance=bottles,
        deposit_balance=deposit,
    )


@router.post("/register", response_model=MeOut)
async def register(
    payload: RegisterIn,
    user: TelegramUser = Depends(telegram_user),
    users: UserService = Depends(get_user_service),
    brand_name: str = Depends(get_brand_name),
) -> MeOut:
    try:
        db_user = await users.register(
            RegistrationInput(
                telegram_id=user.id,
                full_name=payload.full_name,
                phone_number=payload.phone_number,
            )
        )
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    cashback, bottles, deposit = _balance_or_zero(db_user)
    return MeOut(
        telegram_id=user.id,
        is_registered=True,
        full_name=db_user.full_name,
        phone_number=db_user.phone_number,
        tg_first_name=user.first_name,
        tg_last_name=user.last_name,
        tg_username=user.username,
        brand_name=brand_name,
        cashback_balance=cashback,
        bottles_balance=bottles,
        deposit_balance=deposit,
    )


@router.get("/balance", response_model=BalanceOut)
async def get_balance(
    user: TelegramUser = Depends(telegram_user),
    ledger: LedgerService = Depends(get_ledger_service),
) -> BalanceOut:
    """Mijozning real-time keshbek va idishlar balansi.

    Eshigi ochiq sahifalarda alohida poll qilinmaydi — `/api/me` ham bu
    qiymatlarni o'z ichiga oladi. Ammo balans muhim (checkout sahifasi) joylarda
    fresh ko'rinish uchun shu endpoint kerak.
    """
    view = await ledger.get_balance(user.id)
    return BalanceOut(
        cashback_balance=view.cashback_balance,
        bottles_balance=view.bottles_balance,
        cashback_enabled=view.cashback_enabled,
        cashback_percent=view.cashback_percent,
        max_cashback_usage_ratio=view.max_cashback_usage_ratio,
        cashback_use_unit=view.cashback_use_unit,
        deposit_balance=view.deposit_balance,
    )
