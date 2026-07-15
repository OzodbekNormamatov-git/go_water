"""Admin rasxodlar API — /api/admin/expenses/* (P&L moduli).

Uch resurs:
  * kategoriyalar  — /categories (CRUD, soft-delete)
  * doimiy shablon — /recurring  (CRUD; davrlar avtomatik materializatsiya)
  * yozuvlar       — /            (davr bo'yicha ro'yxat/xulosa, CRUD)

Barchasi admin-only (moliyaviy ma'lumot — operator ko'rmaydi).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from Service.exceptions import (
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from Service.expense_service import ExpenseService, local_today
from webapp.admin.auth import admin_required
from webapp.auth import TelegramUser
from webapp.deps import get_expense_service
from webapp.pagination import Page

router = APIRouter(prefix="/api/admin/expenses", tags=["admin:expenses"])


# ---------------------- Schemas ----------------------

class CategoryOut(BaseModel):
    id: int
    name: str
    archived: bool = False


class CategoryIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)


class RecurringOut(BaseModel):
    id: int
    category_id: int
    category_name: str = ""
    label: str = ""
    amount: Decimal
    period: str
    anchor_day: int
    anchor_month: Optional[int] = None
    start_date: str
    end_date: Optional[str] = None
    archived: bool = False


class RecurringIn(BaseModel):
    category_id: int = Field(gt=0)
    label: str = Field(default="", max_length=120)
    amount: Decimal = Field(gt=0)
    period: str = Field(default="monthly", pattern="^(monthly|weekly|yearly)$")
    anchor_day: int = Field(default=1, ge=0, le=31)
    anchor_month: Optional[int] = Field(default=None, ge=1, le=12)
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class RecurringPatchIn(BaseModel):
    label: Optional[str] = Field(default=None, max_length=120)
    amount: Optional[Decimal] = Field(default=None, gt=0)
    end_date: Optional[date] = None
    clear_end_date: bool = False


class ExpenseOut(BaseModel):
    id: int
    category_id: int
    category_name: str = ""
    amount: Decimal
    spent_on: str
    note: str = ""
    recurring_id: Optional[int] = None
    created_by: Optional[int] = None
    # Qamrov davri (oldindan to'langan rasxod) — NULL = oddiy yozuv.
    period_start: Optional[str] = None
    period_end: Optional[str] = None


class ExpenseIn(BaseModel):
    category_id: int = Field(gt=0)
    amount: Decimal = Field(gt=0)
    spent_on: date
    note: str = Field(default="", max_length=255)
    # Ixtiyoriy qamrov davri: to'ldirilsa hisobot summani davr kunlariga
    # proportsional taqsimlaydi (oldindan to'langan oylik/ijara uchun).
    period_start: Optional[date] = None
    period_end: Optional[date] = None


class ExpensePatchIn(BaseModel):
    category_id: Optional[int] = Field(default=None, gt=0)
    amount: Optional[Decimal] = Field(default=None, gt=0)
    spent_on: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=255)
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    # True — qamrov davrini olib tashlash (oddiy rasxodga qaytarish).
    clear_period: bool = False


class CategorySumOut(BaseModel):
    category_id: int
    name: str
    total: float


class ExpenseSummaryOut(BaseModel):
    since: str
    until: str
    total: float
    by_category: List[CategorySumOut] = []


def _to_category(c) -> CategoryOut:
    return CategoryOut(id=c.id, name=c.name, archived=c.is_deleted)


def _to_recurring(r) -> RecurringOut:
    return RecurringOut(
        id=r.id,
        category_id=r.category_id,
        category_name=(r.category.name if r.category else ""),
        label=r.label or "",
        amount=r.amount,
        period=r.period.value if hasattr(r.period, "value") else str(r.period),
        anchor_day=int(r.anchor_day or 1),
        anchor_month=r.anchor_month,
        start_date=r.start_date.isoformat(),
        end_date=r.end_date.isoformat() if r.end_date else None,
        archived=r.is_deleted,
    )


def _to_expense(e) -> ExpenseOut:
    return ExpenseOut(
        id=e.id,
        category_id=e.category_id,
        category_name=(e.category.name if e.category else ""),
        amount=e.amount,
        spent_on=e.spent_on.isoformat(),
        note=e.note or "",
        recurring_id=e.recurring_id,
        created_by=e.created_by,
        period_start=e.period_start.isoformat() if e.period_start else None,
        period_end=e.period_end.isoformat() if e.period_end else None,
    )


def _period_window(year: Optional[int], month: Optional[int]) -> tuple[date, date]:
    """Davr oynasi (mahalliy sana semantikasi, spent_on bilan bir xil):

      * year + month  → o'sha oy
      * faqat year    → butun yil (frontend yillik rejimi bilan mos)
      * hech biri     → joriy oy (mahalliy "bugun" bo'yicha, UTC emas)
    """
    import calendar
    today = local_today()
    y = year or today.year
    if month is None:
        if year is not None:
            return date(y, 1, 1), date(y, 12, 31)
        m = today.month
    else:
        m = month
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


# ---------------------- Kategoriyalar ----------------------

@router.get("/categories", response_model=List[CategoryOut])
async def list_categories(
    _=Depends(admin_required),
    include_archived: bool = Query(default=False),
    svc: ExpenseService = Depends(get_expense_service),
) -> List[CategoryOut]:
    cats = await svc.list_categories(include_archived=include_archived)
    return [_to_category(c) for c in cats]


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryIn,
    _=Depends(admin_required),
    svc: ExpenseService = Depends(get_expense_service),
) -> CategoryOut:
    try:
        cat = await svc.create_category(payload.name)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_category(cat)


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def rename_category(
    category_id: int,
    payload: CategoryIn,
    _=Depends(admin_required),
    svc: ExpenseService = Depends(get_expense_service),
) -> CategoryOut:
    try:
        cat = await svc.rename_category(category_id, payload.name)
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Kategoriya topilmadi")
    except InvalidOperationError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_category(cat)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=None)
async def archive_category(
    category_id: int,
    _=Depends(admin_required),
    svc: ExpenseService = Depends(get_expense_service),
):
    from fastapi.responses import Response
    try:
        await svc.archive_category(category_id)
    except InvalidOperationError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------- Doimiy shablonlar ----------------------

@router.get("/recurring", response_model=List[RecurringOut])
async def list_recurring(
    _=Depends(admin_required),
    include_archived: bool = Query(default=False),
    svc: ExpenseService = Depends(get_expense_service),
) -> List[RecurringOut]:
    recs = await svc.list_recurring(include_archived=include_archived)
    return [_to_recurring(r) for r in recs]


@router.post("/recurring", response_model=RecurringOut, status_code=status.HTTP_201_CREATED)
async def create_recurring(
    payload: RecurringIn,
    _=Depends(admin_required),
    svc: ExpenseService = Depends(get_expense_service),
) -> RecurringOut:
    try:
        rec = await svc.create_recurring(
            category_id=payload.category_id,
            label=payload.label,
            amount=payload.amount,
            period=payload.period,
            anchor_day=payload.anchor_day,
            anchor_month=payload.anchor_month,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Kategoriya topilmadi")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_recurring(rec)


@router.patch("/recurring/{recurring_id}", response_model=RecurringOut)
async def update_recurring(
    recurring_id: int,
    payload: RecurringPatchIn,
    _=Depends(admin_required),
    svc: ExpenseService = Depends(get_expense_service),
) -> RecurringOut:
    try:
        rec = await svc.update_recurring(
            recurring_id,
            label=payload.label,
            amount=payload.amount,
            end_date=payload.end_date,
            clear_end_date=payload.clear_end_date,
        )
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Doimiy rasxod topilmadi")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_recurring(rec)


@router.delete("/recurring/{recurring_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=None)
async def archive_recurring(
    recurring_id: int,
    _=Depends(admin_required),
    svc: ExpenseService = Depends(get_expense_service),
):
    from fastapi.responses import Response
    await svc.archive_recurring(recurring_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------- Yozuvlar ----------------------

@router.get("", response_model=Page[ExpenseOut])
async def list_expenses(
    _=Depends(admin_required),
    year: Optional[int] = Query(default=None, ge=2000, le=2100),
    month: Optional[int] = Query(default=None, ge=1, le=12),
    category_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    svc: ExpenseService = Depends(get_expense_service),
) -> Page[ExpenseOut]:
    since, until = _period_window(year, month)
    items, total = await svc.list_expenses(
        since, until, category_id=category_id, limit=limit, offset=offset,
    )
    return Page[ExpenseOut](
        items=[_to_expense(e) for e in items],
        total=total, limit=limit, offset=offset,
    )


@router.get("/summary", response_model=ExpenseSummaryOut)
async def expenses_summary(
    _=Depends(admin_required),
    year: Optional[int] = Query(default=None, ge=2000, le=2100),
    month: Optional[int] = Query(default=None, ge=1, le=12),
    svc: ExpenseService = Depends(get_expense_service),
) -> ExpenseSummaryOut:
    since, until = _period_window(year, month)
    s = await svc.summary(since, until)
    return ExpenseSummaryOut(
        since=since.isoformat(), until=until.isoformat(),
        total=float(s.total),
        by_category=[
            CategorySumOut(category_id=cid, name=name, total=float(total))
            for cid, name, total in s.by_category
        ],
    )


@router.post("", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
async def add_expense(
    payload: ExpenseIn,
    user: TelegramUser = Depends(admin_required),
    svc: ExpenseService = Depends(get_expense_service),
) -> ExpenseOut:
    try:
        exp = await svc.add_expense(
            category_id=payload.category_id,
            amount=payload.amount,
            spent_on=payload.spent_on,
            note=payload.note,
            created_by=int(user.id),
            period_start=payload.period_start,
            period_end=payload.period_end,
        )
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Kategoriya topilmadi")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_expense(exp)


@router.patch("/{expense_id}", response_model=ExpenseOut)
async def update_expense(
    expense_id: int,
    payload: ExpensePatchIn,
    _=Depends(admin_required),
    svc: ExpenseService = Depends(get_expense_service),
) -> ExpenseOut:
    try:
        exp = await svc.update_expense(
            expense_id,
            amount=payload.amount,
            spent_on=payload.spent_on,
            note=payload.note,
            category_id=payload.category_id,
            period_start=payload.period_start,
            period_end=payload.period_end,
            clear_period=payload.clear_period,
        )
    except EntityNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidOperationError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_expense(exp)


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=None)
async def archive_expense(
    expense_id: int,
    _=Depends(admin_required),
    svc: ExpenseService = Depends(get_expense_service),
):
    from fastapi.responses import Response
    await svc.archive_expense(expense_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
