"""Aqlli eslatma API — /api/admin/reorder (operator paneli).

"Aqlli eslatma" — operator "suv olish vaqti kelgan" mijozlarni ko'radi va
qo'ng'iroq natijasini qayd qiladi. Segmentlar: due (vaqti keldi) / overdue
(kechikdi, churn xavfi) / churned (uzoq qaytmagan — win-back). Operator ham,
admin ham kiradi.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from Domain.constants import MAX_REORDER_SNOOZE_DAYS
from Service.customer_lifecycle_service import CustomerLifecycleService
from Service.exceptions import EntityNotFoundError, ValidationError
from webapp.admin.auth import operator_required
from webapp.auth import TelegramUser
from webapp.deps import get_lifecycle_service

router = APIRouter(prefix="/api/admin/reorder", tags=["admin:reorder"])


# ---------------------- Schemas ----------------------

class ReorderItemOut(BaseModel):
    customer_id: int
    telegram_id: int
    full_name: str
    phone_number: str
    segment: str                       # active | due | overdue | churned
    orders_count: int
    last_delivered_at: Optional[str] = None
    cycle_days: Optional[float] = None
    due_date: Optional[str] = None
    days_overdue: int = 0
    reminders_sent: int = 0
    can_dm: bool = False
    has_open_order: bool = False
    snoozed_until: Optional[str] = None
    last_call_at: Optional[str] = None
    last_call_outcome: Optional[str] = None
    last_call_note: str = ""


class ReorderPageOut(BaseModel):
    items: List[ReorderItemOut]
    total: int
    counts: dict                       # segment -> soni (snooze'dagilarsiz)
    limit: int
    offset: int


class CallIn(BaseModel):
    outcome: str = Field(pattern="^(ordered|no_answer|refused|snoozed)$")
    note: str = Field(default="", max_length=255)
    snooze_days: int = Field(default=0, ge=0, le=MAX_REORDER_SNOOZE_DAYS)


class CallOut(BaseModel):
    id: int
    customer_id: int
    operator_id: int
    called_at: str
    outcome: str
    outcome_label: str
    snooze_until: Optional[str] = None
    note: str = ""


def _to_item(it) -> ReorderItemOut:
    return ReorderItemOut(
        customer_id=it.customer_id,
        telegram_id=it.telegram_id,
        full_name=it.full_name,
        phone_number=it.phone_number,
        segment=it.segment,
        orders_count=it.orders_count,
        last_delivered_at=it.last_delivered_at.isoformat() if it.last_delivered_at else None,
        cycle_days=it.cycle_days,
        due_date=it.due_date.isoformat() if it.due_date else None,
        days_overdue=it.days_overdue,
        reminders_sent=it.reminders_sent,
        can_dm=it.can_dm,
        has_open_order=it.has_open_order,
        snoozed_until=it.snoozed_until.isoformat() if it.snoozed_until else None,
        last_call_at=it.last_call_at.isoformat() if it.last_call_at else None,
        last_call_outcome=it.last_call_outcome,
        last_call_note=it.last_call_note or "",
    )


def _to_call(c) -> CallOut:
    return CallOut(
        id=c.id,
        customer_id=c.customer_id,
        operator_id=c.operator_id,
        called_at=c.called_at.isoformat() if c.called_at else "",
        outcome=c.outcome.value,
        outcome_label=c.outcome.label_uz,
        snooze_until=c.snooze_until.isoformat() if c.snooze_until else None,
        note=c.note or "",
    )


# ---------------------- Endpoints ----------------------

@router.get("", response_model=ReorderPageOut)
async def reorder_list(
    _user: TelegramUser = Depends(operator_required),
    segment: Optional[str] = Query(
        default=None, pattern="^(all|active|due|overdue|churned)$",
    ),
    include_snoozed: bool = Query(default=False),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    svc: CustomerLifecycleService = Depends(get_lifecycle_service),
) -> ReorderPageOut:
    """Aqlli eslatma ro'yxati. Default — harakat talab qiladigan segmentlar
    (due + overdue + churned), eng ko'p kechikkanlar birinchi."""
    page = await svc.reorder_list(
        segment=segment, include_snoozed=include_snoozed,
        limit=limit, offset=offset,
    )
    return ReorderPageOut(
        items=[_to_item(it) for it in page.items],
        total=page.total,
        counts=page.counts,
        limit=limit,
        offset=offset,
    )


@router.post("/{customer_id}/calls", response_model=CallOut, status_code=status.HTTP_201_CREATED)
async def log_call(
    customer_id: int,
    payload: CallIn,
    user: TelegramUser = Depends(operator_required),
    svc: CustomerLifecycleService = Depends(get_lifecycle_service),
) -> CallOut:
    """Qo'ng'iroq natijasini qayd qilish. `snooze_days` — shuncha kun ro'yxatdan
    yashirish (masalan, mijoz "3 kundan keyin" desa)."""
    try:
        call = await svc.log_call(
            customer_id,
            operator_id=int(user.id),
            outcome=payload.outcome,
            note=payload.note,
            snooze_days=payload.snooze_days,
        )
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Mijoz topilmadi")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_call(call)


@router.get("/{customer_id}/calls", response_model=List[CallOut])
async def call_history(
    customer_id: int,
    _user: TelegramUser = Depends(operator_required),
    limit: int = Query(default=20, le=100),
    svc: CustomerLifecycleService = Depends(get_lifecycle_service),
) -> List[CallOut]:
    """Mijozning qo'ng'iroqlar tarixi (oxirgilari birinchi)."""
    calls = await svc.call_history(customer_id, limit=limit)
    return [_to_call(c) for c in calls]
