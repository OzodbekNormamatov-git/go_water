"""Markaziy ledger posting — balansni o'zgartirishning YAGONA nuqtasi.

Har bir balans o'zgarishi shu funksiya orqali amalga oshiriladi:
  1. Keshlangan balans ustuni (`user.cashback_balance` / `bottles_balance` /
     `courier.cash_balance`) yangilanadi
  2. Append-only `ledger_entries` jadvaliga `balance_after` bilan yozuv qo'shiladi

Shu tariqa kesh ustun va jurnal HECH QACHON ajralib qolmaydi (ikkalasi bitta
tranzaksiyada). Subyekt (`User`/`Courier`) caller tomonidan ALLAQACHON
`get_for_update` bilan LOCK qilingan bo'lishi shart — bu funksiya qo'shimcha
lock olmaydi (mavjud atomik bloklarga qo'shiladi).

Idempotency: `idempotency_key` berilsa va shu kalit bilan yozuv mavjud bo'lsa,
hech narsa o'zgartirilmaydi (mavjud yozuv qaytariladi) — takroriy chaqiruv
balansni ikki marta surmaydi.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from Domain.models.courier import Courier
from Domain.models.ledger import LedgerAccount, LedgerEntry, LedgerKind, LedgerSubject
from Domain.models.user import User
from Service.exceptions import InvalidOperationError

# Account → keshlangan balans ustuni nomi.
_ACCOUNT_COLUMN = {
    LedgerAccount.CASHBACK: "cashback_balance",
    LedgerAccount.BOTTLES: "bottles_balance",
    LedgerAccount.CASH: "cash_balance",
    LedgerAccount.DEPOSIT: "deposit_balance",
}


def _subject_type_of(subject) -> LedgerSubject:
    if isinstance(subject, User):
        return LedgerSubject.USER
    if isinstance(subject, Courier):
        return LedgerSubject.COURIER
    raise TypeError(f"Ledger subyekti User yoki Courier bo'lishi shart: {type(subject)!r}")


async def post_ledger(
    uow,
    *,
    subject,
    account: LedgerAccount,
    kind: LedgerKind,
    delta,
    order_id: Optional[int] = None,
    operator_id: Optional[int] = None,
    reason: str = "",
    idempotency_key: Optional[str] = None,
    clamp_zero: bool = False,
) -> LedgerEntry:
    """Balansni `delta` ga o'zgartiradi va jurnal yozuvini qo'shadi.

    * `subject` — LOCK qilingan `User` yoki `Courier`.
    * `delta` — ishorali (musbat = qo'shish, manfiy = ayirish). Decimal/int/str.
    * `clamp_zero=True` — balans manfiyga tushsa 0 ga qiriqiladi (idish DELIVERED
      uchun himoya). Aks holda manfiy balans `InvalidOperationError` chiqaradi.
    * `idempotency_key` — takroriy yozuvni bloklaydi.
    """
    subject_type = _subject_type_of(subject)
    subject_id = int(subject.id)

    if idempotency_key:
        existing = await uow.ledger.get_by_idempotency_key(
            subject_type.value, subject_id, account.value, idempotency_key,
        )
        if existing is not None:
            return existing

    col = _ACCOUNT_COLUMN[account]
    current = Decimal(str(getattr(subject, col) or 0))
    delta_d = Decimal(str(delta or 0))
    new = current + delta_d

    if new < 0:
        if clamp_zero:
            # Haqiqatda qo'llangan delta — 0 ga yetkazadigan miqdor (jurnal
            # invarianti saqlanadi: balance_after = oldingi + delta).
            delta_d = -current
            new = Decimal("0")
        else:
            raise InvalidOperationError(
                "balance_negative",
                context={"account": account.value, "available": float(current)},
            )

    # Keshlangan ustunni yangilaymiz (idish — butun son).
    if account == LedgerAccount.BOTTLES:
        setattr(subject, col, int(new))
    else:
        setattr(subject, col, new.quantize(Decimal("0.01")))
    uow.session.add(subject)

    entry = LedgerEntry(
        subject_type=subject_type.value,
        subject_id=subject_id,
        account=account.value,
        kind=kind.value,
        delta=delta_d.quantize(Decimal("0.01")),
        balance_after=new.quantize(Decimal("0.01")),
        order_id=order_id,
        operator_id=operator_id,
        reason=reason or "",
        idempotency_key=idempotency_key,
    )
    return await uow.ledger.add(entry)
