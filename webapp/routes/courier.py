"""Kuryer Mini App API — /api/courier/*.

Buyurtmalar HAMMA aktiv kuryerga ko'rinadi (polling); birinchi "Olaman" bosgan
oladi. Race-safety mavjud `OrderService.claim_by_courier` (SELECT FOR UPDATE) —
bir vaqtda bir nechta bosilsa ham aniq bitta g'olib. Transitsiyalar ham o'sha
service metodlaridan o'tadi; bot va web bir xil mantiqqa tayanadi.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from Data.unit_of_work import UnitOfWork
from Domain.constants import MAX_BOTTLES_ISSUED_PER_ORDER, MAX_QUANTITY_PER_ITEM
from Domain.enums import OrderStatus
from Service.courier_flow_service import CourierFlowService
from Service.exceptions import DomainError, EntityNotFoundError, InvalidOperationError
from Service.order_display import order_display_number
from Service.order_service import OrderService
from webapp.deps import (
    current_courier,
    get_courier_flow_service,
    get_order_service,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/courier", tags=["courier"])


# ---------------------- Schemas ----------------------

class CourierMeOut(BaseModel):
    id: int
    full_name: str
    phone_number: Optional[str] = None
    is_active: bool
    cash_balance: Decimal = Decimal("0.00")
    active_order_id: Optional[int] = None


class CourierItemOut(BaseModel):
    # id — kuryer yetkazilgan miqdorni o'zgartirish uchun (delivered-items).
    id: int
    food_name: str
    # quantity — AMALDAGI (yetkazilgan) dona; delivered o'zgartirilmagan bo'lsa
    # buyurtilganga teng. ordered_quantity — mijoz boshida buyurtma qilgan.
    quantity: int
    ordered_quantity: int
    unit_price: Decimal


class CourierOrderOut(BaseModel):
    id: int
    display_number: str
    status: str
    status_label: str
    total_amount: Decimal
    items: List[CourierItemOut] = []
    latitude: float
    longitude: float
    map_url: str
    address_label: str = ""
    address_details: str = ""
    note: str = ""
    bottles_issued: int = 0
    bottles_returned: int = 0
    created_at: Optional[str] = None
    # Faqat biriktirilgan kuryerga (active/claim) — mijoz telefoni:
    contact_phone: Optional[str] = None
    # Mijozning TARIXDA yig'ilgan idishlari — "qaytarib olindi" stepperining
    # yuqori chegarasi (kuryer bundan ortiq qaytarib ololmaydi). Faqat
    # biriktirilgan kuryerga (NEW ro'yxatida yuborilmaydi).
    customer_bottles_balance: Optional[int] = None
    # To'lov usuli — kuryer eshik oldida naqd olish/olmasligini OLDINDAN biladi:
    #   cash    → "💵 Naqd" (kuryer pul oladi)
    #   card    → "💳 Karta" (pul olinmaydi)
    #   deposit → "💰 Balansdan to'langan" (pul olinmaydi)
    payment_method: str = "cash"
    payment_method_label: str = "Naqd"
    # True — kuryer mijozdan naqd olishi kerak (faqat cash'da).
    collect_cash: bool = True


class BottlesIn(BaseModel):
    """Qaytarilgan idishlar — cap BERILGANLAR bilan bir xil: katta buyurtmada
    (100+ idish) mijoz 50 tadan ortiq bo'sh idish qaytarishi qonuniy holat.
    Balansdan oshiq qaytarish DELIVERED'da baribir clamp_zero bilan himoyalangan."""
    value: int = Field(ge=0, le=MAX_BOTTLES_ISSUED_PER_ORDER)


class DeliveredItemIn(BaseModel):
    item_id: int = Field(gt=0)
    quantity: int = Field(ge=0, le=MAX_QUANTITY_PER_ITEM)


class DeliveredItemsIn(BaseModel):
    """Kuryer yetkazgan haqiqiy miqdorlar — order moliyasi noldan hisoblanadi."""
    items: List[DeliveredItemIn] = Field(min_length=1)


class PaymentMethodIn(BaseModel):
    """Kuryer yakuniy to'lov usulini tanlaydi — faqat naqd yoki karta."""
    method: str = Field(pattern="^(cash|card)$")


def _to_courier_order(o, *, include_phone: bool) -> CourierOrderOut:
    from Domain.enums import PaymentMethod
    pm_raw = str(getattr(o, "payment_method", "cash") or "cash")
    try:
        pm = PaymentMethod(pm_raw)
    except ValueError:
        pm = PaymentMethod.CASH
    return CourierOrderOut(
        id=o.id,
        display_number=order_display_number(o),
        status=o.status.name,
        status_label=o.status.label_uz,
        total_amount=o.total_amount,
        payment_method=pm.value,
        payment_method_label=f"{pm.emoji} {pm.label_uz}",
        collect_cash=(pm == PaymentMethod.CASH),
        items=[
            CourierItemOut(
                id=it.id,
                food_name=it.food_name,
                quantity=int(it.effective_quantity),
                ordered_quantity=int(it.quantity),
                unit_price=it.unit_price,
            )
            for it in (o.items or [])
        ],
        latitude=float(o.delivery_latitude),
        longitude=float(o.delivery_longitude),
        map_url=f"https://maps.google.com/?q={o.delivery_latitude},{o.delivery_longitude}",
        address_label=o.address_label or "",
        address_details=o.address_details or "",
        note=o.note or "",
        bottles_issued=int(o.bottles_issued or 0),
        bottles_returned=int(o.bottles_returned or 0),
        created_at=o.created_at.isoformat() if o.created_at else None,
        contact_phone=(o.contact_phone if include_phone else None),
        # Mijoz idish balansi (relationship selectin bilan yuklangan) —
        # qaytarish stepperining cheg'arasi. Faqat biriktirilgan kuryerga.
        customer_bottles_balance=(
            int(getattr(getattr(o, "customer", None), "bottles_balance", 0) or 0)
            if include_phone else None
        ),
    )


# ---------------------- Read ----------------------

@router.get("/me", response_model=CourierMeOut)
async def courier_me(
    courier=Depends(current_courier),
    orders: OrderService = Depends(get_order_service),
) -> CourierMeOut:
    sf = orders._sf  # type: ignore[attr-defined]
    async with UnitOfWork(sf) as uow:
        active = await uow.orders.list_active_by_courier(courier.id)
    active_id = active[0].id if active else None
    return CourierMeOut(
        id=courier.id,
        full_name=courier.full_name,
        phone_number=courier.phone_number,
        is_active=courier.is_active,
        cash_balance=Decimal(courier.cash_balance or 0),
        active_order_id=active_id,
    )


class CourierStatsOut(BaseModel):
    today: int = 0
    month: int = 0
    year: int = 0
    total: int = 0
    cash_balance: Decimal = Decimal("0.00")


@router.get("/stats", response_model=CourierStatsOut)
async def courier_stats(
    courier=Depends(current_courier),
    orders: OrderService = Depends(get_order_service),
) -> CourierStatsOut:
    s = await orders.delivered_stats_for_courier(courier.id)
    return CourierStatsOut(
        today=s.today, month=s.month, year=s.year, total=s.total,
        cash_balance=Decimal(courier.cash_balance or 0),
    )


@router.get("/available", response_model=List[CourierOrderOut])
async def available_orders(
    courier=Depends(current_courier),
    orders: OrderService = Depends(get_order_service),
    limit: int = Query(default=50, le=100),
) -> List[CourierOrderOut]:
    """Hali olinmagan (NEW) buyurtmalar — barcha aktiv kuryerga ko'rinadi."""
    sf = orders._sf  # type: ignore[attr-defined]
    async with UnitOfWork(sf) as uow:
        rows = await uow.orders.list_by_status(OrderStatus.NEW, limit=limit)
    # NEW buyurtmada mijoz telefoni ko'rsatilmaydi (hali biriktirilmagan).
    return [_to_courier_order(o, include_phone=False) for o in rows]


@router.get("/active", response_model=List[CourierOrderOut])
async def active_orders(
    courier=Depends(current_courier),
    orders: OrderService = Depends(get_order_service),
) -> List[CourierOrderOut]:
    """Kuryerning hozirgi (tugallanmagan) buyurtmalari — to'liq, telefon bilan."""
    sf = orders._sf  # type: ignore[attr-defined]
    async with UnitOfWork(sf) as uow:
        rows = await uow.orders.list_active_by_courier(courier.id)
    return [_to_courier_order(o, include_phone=True) for o in rows]


# ---------------------- Claim + transitions (CourierFlowService orqali) ----------------------
# Route'lar yupqa: biznes oqim (holat + bildirishnomalar) CourierFlowService'da.

def _http_for(exc: DomainError) -> HTTPException:
    if isinstance(exc, EntityNotFoundError):
        return HTTPException(status_code=404, detail="Buyurtma topilmadi")
    if isinstance(exc, InvalidOperationError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.post("/orders/{order_id}/claim", response_model=CourierOrderOut)
async def claim_order(
    order_id: int,
    courier=Depends(current_courier),
    flow: CourierFlowService = Depends(get_courier_flow_service),
) -> CourierOrderOut:
    """Buyurtmani olish — race-safe (SELECT FOR UPDATE). Boshqa kuryer ulgursa 409."""
    try:
        order = await flow.claim(courier, order_id)
    except DomainError as e:
        raise _http_for(e)
    return _to_courier_order(order, include_phone=True)


@router.post("/orders/{order_id}/delivering", response_model=CourierOrderOut)
async def mark_delivering(
    order_id: int,
    courier=Depends(current_courier),
    flow: CourierFlowService = Depends(get_courier_flow_service),
) -> CourierOrderOut:
    try:
        order = await flow.mark_delivering(courier, order_id)
    except DomainError as e:
        raise _http_for(e)
    return _to_courier_order(order, include_phone=True)


@router.post("/orders/{order_id}/arrived", response_model=CourierOrderOut)
async def mark_arrived(
    order_id: int,
    courier=Depends(current_courier),
    flow: CourierFlowService = Depends(get_courier_flow_service),
) -> CourierOrderOut:
    try:
        order = await flow.mark_arrived(courier, order_id)
    except DomainError as e:
        raise _http_for(e)
    return _to_courier_order(order, include_phone=True)


@router.post("/orders/{order_id}/bottles", response_model=CourierOrderOut)
async def set_bottles(
    order_id: int,
    payload: BottlesIn,
    courier=Depends(current_courier),
    flow: CourierFlowService = Depends(get_courier_flow_service),
) -> CourierOrderOut:
    """Yetkazishdan oldin mijozdan olingan bo'sh idishlar sonini kiritish."""
    try:
        order = await flow.set_bottles(courier, order_id, payload.value)
    except DomainError as e:
        raise _http_for(e)
    return _to_courier_order(order, include_phone=True)


@router.post("/orders/{order_id}/delivered-items", response_model=CourierOrderOut)
async def set_delivered_items(
    order_id: int,
    payload: DeliveredItemsIn,
    courier=Depends(current_courier),
    flow: CourierFlowService = Depends(get_courier_flow_service),
) -> CourierOrderOut:
    """Kuryer HAQIQATDA yetkazgan dona sonini kiritish (ARRIVED holatda).

    Mijoz "4 ta" deb buyurtma qilib 6 ta olsa — order NOLDAN qayta hisoblanadi:
    narx, keshbek, idish soni va kuryer naqdi to'g'ri summaga moslanadi. Javob —
    yangilangan order (total_amount o'zgargan bo'lishi mumkin)."""
    quantities = {it.item_id: it.quantity for it in payload.items}
    try:
        order = await flow.set_delivered_quantities(courier, order_id, quantities)
    except DomainError as e:
        raise _http_for(e)
    return _to_courier_order(order, include_phone=True)


@router.post("/orders/{order_id}/payment-method", response_model=CourierOrderOut)
async def set_payment_method(
    order_id: int,
    payload: PaymentMethodIn,
    courier=Depends(current_courier),
    flow: CourierFlowService = Depends(get_courier_flow_service),
) -> CourierOrderOut:
    """Kuryer yakuniy to'lov usulini tanlaydi (naqd/karta, ARRIVED holatda).

    Mijoz "naqd" degan bo'lsa ham eshik oldida kartadan to'lashi mumkin —
    kuryer oxirgi qarorni kiritadi. Depozit buyurtmalar o'zgartirilmaydi."""
    try:
        order = await flow.set_payment_method(courier, order_id, payload.method)
    except DomainError as e:
        raise _http_for(e)
    return _to_courier_order(order, include_phone=True)


@router.post("/orders/{order_id}/delivered", response_model=CourierOrderOut)
async def mark_delivered(
    order_id: int,
    courier=Depends(current_courier),
    flow: CourierFlowService = Depends(get_courier_flow_service),
) -> CourierOrderOut:
    """Yetkazib berildi — balans/jurnal yangilanadi (race-safe, order LOCK)."""
    try:
        order = await flow.mark_delivered(courier, order_id)
    except DomainError as e:
        raise _http_for(e)
    return _to_courier_order(order, include_phone=True)
