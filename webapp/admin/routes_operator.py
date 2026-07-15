"""Operator API — call operator buyurtma yaratish va mijoz qidirish.

Endpoint'lar:
  GET   /api/admin/operator/customer-lookup?phone=...  — mijozni telefonda topish
  POST  /api/admin/operator/orders                     — buyurtma yaratish

Admin'lar ham bu endpoint'lardan foydalanishlari mumkin (`operator_required`).
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from Data.unit_of_work import UnitOfWork
from Domain.constants import (
    LAT_MAX, LAT_MIN, LON_MAX, LON_MIN,
    MAX_ADDRESS_DETAILS_LENGTH, MAX_ADDRESS_LABEL_LENGTH,
    MAX_BOTTLES_PER_TRANSACTION, MAX_ITEMS_PER_ORDER, MAX_NOTE_LENGTH,
    MAX_QUANTITY_PER_ITEM, MIN_QUANTITY_PER_ITEM,
)
from Service.exceptions import (
    DomainError, InvalidOperationError, ValidationError,
)
from Service.notification_service import NotificationService
from Service.order_display import order_display_number
from Service.order_service import CartItem, NewOrderInput, OrderService
from Service.user_service import UserService
from webapp.admin.auth import operator_required
from webapp.auth import TelegramUser
from webapp.deps import (
    get_notification_service, get_order_service, get_user_service,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/operator", tags=["admin:operator"])


# ---------------------- Schemas ----------------------

class CustomerLookupOut(BaseModel):
    """Telefonda topilgan mijozning qisqacha info'si."""
    found: bool
    id: Optional[int] = None
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    has_started_bot: bool = False
    cashback_balance: Decimal = Decimal("0.00")
    bottles_balance: int = 0
    # Avans (depozit) balansi — operator "Balansdan" to'lovni taklif qila olishi uchun.
    deposit_balance: Decimal = Decimal("0.00")


class CustomerHit(BaseModel):
    """Qidiruv natijasidagi bitta mijoz (ism/telefon bo'yicha)."""
    id: int
    full_name: str
    phone_number: str
    has_started_bot: bool = False
    cashback_balance: Decimal = Decimal("0.00")
    bottles_balance: int = 0
    deposit_balance: Decimal = Decimal("0.00")


class OperatorOrderItemIn(BaseModel):
    food_id: int = Field(gt=0)
    quantity: int = Field(ge=MIN_QUANTITY_PER_ITEM, le=MAX_QUANTITY_PER_ITEM)


class OperatorOrderIn(BaseModel):
    # Mijoz ma'lumotlari (telefon orqali topish + yangi mijoz uchun ism)
    customer_phone: str = Field(min_length=4, max_length=24)
    customer_full_name: str = Field(min_length=2, max_length=120)
    # Buyurtma tarkibi
    items: List[OperatorOrderItemIn] = Field(min_length=1, max_length=MAX_ITEMS_PER_ORDER)
    # Yetkazib berish manzili
    latitude: float = Field(ge=LAT_MIN, le=LAT_MAX)
    longitude: float = Field(ge=LON_MIN, le=LON_MAX)
    address_label: str = Field(default="", max_length=MAX_ADDRESS_LABEL_LENGTH)
    address_details: str = Field(default="", max_length=MAX_ADDRESS_DETAILS_LENGTH)
    # Aloqa va izoh
    contact_phone: str = Field(min_length=4, max_length=24)
    note: str = Field(min_length=1, max_length=MAX_NOTE_LENGTH)
    # Mijoz balansidan ishlatiladigan keshbek va idishlar
    cashback_to_use: Decimal = Field(default=Decimal("0.00"), ge=0)
    bottles_returned: int = Field(default=0, ge=0, le=MAX_BOTTLES_PER_TRANSACTION)
    # To'lov usuli: cash (default) | card | deposit (mijoz avans balansidan).
    payment_method: str = Field(default="cash", pattern="^(cash|card|deposit)$")
    # Operator UI retry'lari duplikat buyurtma yaratmasligi uchun (mijoz API bilan parity).
    idempotency_key: Optional[str] = Field(default=None, max_length=64)


class OperatorOrderOut(BaseModel):
    """Yaratilgan buyurtmaning qisqacha info'si (operator UI uchun)."""
    id: int
    display_number: str
    status: str
    total_amount: Decimal
    customer_id: int
    customer_full_name: str
    customer_has_started_bot: bool
    created_by_operator_id: int


class RecentOrderItemOut(BaseModel):
    """Takror buyurtma uchun bitta mahsulot snapshot'i (buyurtma vaqtidagi)."""
    food_id: Optional[int] = None
    food_name: str
    quantity: int
    unit_price: Decimal


class RecentOrderOut(BaseModel):
    """Mijozning o'tgan buyurtmasi — operator "takrorlash" uchun ko'radi."""
    id: int
    display_number: str
    status: str
    status_label: str
    total_amount: Decimal
    created_at: Optional[str] = None
    latitude: float
    longitude: float
    address_label: str = ""
    address_details: str = ""
    contact_phone: str = ""
    note: str = ""
    items: List[RecentOrderItemOut] = []


# ---------------------- Endpoints ----------------------

@router.get("/customer-lookup", response_model=CustomerLookupOut)
async def customer_lookup(
    phone: str = Query(min_length=4, max_length=24),
    _user: TelegramUser = Depends(operator_required),
    users: UserService = Depends(get_user_service),
) -> CustomerLookupOut:
    """Telefonda mijozni topish — operator yangi buyurtma yaratayotganda
    ma'lumotni avtomatik to'ldirish uchun. Topilmasa `found=false`.

    ISTALGAN raqam bo'yicha izlaydi (primary yoki qo'shimcha) — mijoz boshqa
    raqamidan qo'ng'iroq qilsa ham topiladi (user_phones)."""
    u = await users.find_by_any_phone_raw(phone)
    if u is None or u.is_deleted:
        return CustomerLookupOut(found=False)
    return CustomerLookupOut(
        found=True,
        id=u.id,
        full_name=u.full_name,
        phone_number=u.phone_number,
        has_started_bot=bool(u.has_started_bot),
        cashback_balance=Decimal(u.cashback_balance or 0),
        bottles_balance=int(u.bottles_balance or 0),
        deposit_balance=Decimal(getattr(u, "deposit_balance", 0) or 0),
    )


@router.get("/customer-search", response_model=List[CustomerHit])
async def customer_search(
    q: str = Query(min_length=2, max_length=64),
    _user: TelegramUser = Depends(operator_required),
    users: UserService = Depends(get_user_service),
    limit: int = Query(default=8, ge=1, le=20),
) -> List[CustomerHit]:
    """Operator mijozni ism YOKI telefon (qisman, oxirgi raqamlar) bo'yicha qidiradi.
    Barcha raqamlar (user_phones) hisobga olinadi. Operator ro'yxatdan tanlaydi.

    SIYOSAT: bu javobda balanslar (keshbek/idish/depozit) ATAYLAB qaytariladi —
    operator buyurtma yaratishда keshbek/depozit taklif qilishi uchun zarur
    (limit<=20 + qidiruv niyati bilan cheklangan). Bulk ro'yxat (GET
    /api/admin/customers) esa operatorga balanslarni 0 qilib beradi."""
    rows = await users.search_customers(q, limit=limit)
    return [
        CustomerHit(
            id=u.id,
            full_name=u.full_name,
            phone_number=u.phone_number,
            has_started_bot=bool(u.has_started_bot),
            cashback_balance=Decimal(u.cashback_balance or 0),
            bottles_balance=int(u.bottles_balance or 0),
            deposit_balance=Decimal(getattr(u, "deposit_balance", 0) or 0),
        )
        for u in rows
    ]


@router.get("/customers/{customer_id}/recent-orders", response_model=List[RecentOrderOut])
async def customer_recent_orders(
    customer_id: int,
    _user: TelegramUser = Depends(operator_required),
    orders: OrderService = Depends(get_order_service),
    limit: int = Query(default=3, ge=1, le=20),
) -> List[RecentOrderOut]:
    """Mijozning oxirgi buyurtmalari — operator "takrorlash" uchun ko'radi.

    Items snapshot bilan qaytariladi (buyurtma vaqtidagi nom/narx). Operator UI
    bu itemlarni JORIY katalogga moslab (mavjudlik/narx/min) takrorlaydi —
    mavjud `POST /orders` quvuridan o'tadi (bitta yozish yo'li).
    """
    sf = orders._sf  # type: ignore[attr-defined]
    async with UnitOfWork(sf) as uow:
        rows = await uow.orders.list_by_customer_paginated(
            customer_id, limit=limit, offset=0,
        )
        return [
            RecentOrderOut(
                id=o.id,
                display_number=order_display_number(o),
                status=o.status.name,
                status_label=o.status.label_uz,
                total_amount=o.total_amount,
                created_at=o.created_at.isoformat() if o.created_at else None,
                latitude=float(o.delivery_latitude),
                longitude=float(o.delivery_longitude),
                address_label=o.address_label or "",
                address_details=o.address_details or "",
                contact_phone=o.contact_phone or "",
                note=o.note or "",
                items=[
                    RecentOrderItemOut(
                        food_id=it.food_id,
                        food_name=it.food_name,
                        quantity=it.quantity,
                        unit_price=it.unit_price,
                    )
                    for it in (o.items or [])
                ],
            )
            for o in rows
        ]


@router.post("/orders", response_model=OperatorOrderOut, status_code=status.HTTP_201_CREATED)
async def create_operator_order(
    payload: OperatorOrderIn,
    user: TelegramUser = Depends(operator_required),
    users: UserService = Depends(get_user_service),
    orders: OrderService = Depends(get_order_service),
    notifier: NotificationService = Depends(get_notification_service),
) -> OperatorOrderOut:
    """Operator yangi buyurtma yaratadi (mijoz nomidan).

    Oqim:
      1) Mijozni telefonda topamiz; yo'q bo'lsa yangi (guest) mijoz yaratamiz
         (sintetik manfiy `telegram_id`, `has_started_bot=False`)
      2) Buyurtma yaratamiz (`created_by_operator_id = operator.id`)
      3) Kuryerlar guruhiga xabar yuboramiz (oddiy)
      4) Mijozga DM xabar — faqat `has_started_bot=True` bo'lsa
    """
    # 1) Mijozni topish / yaratish
    try:
        customer = await users.find_or_create_for_operator(
            full_name=payload.customer_full_name,
            phone_number=payload.customer_phone,
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 2) Buyurtma yaratish — OrderService.create_order customer_telegram_id orqali
    #    izlaydi, biz uning real (yoki sintetik) ID sini uzatamiz.
    try:
        order = await orders.create_order(NewOrderInput(
            customer_telegram_id=customer.telegram_id,
            items=[CartItem(food_id=i.food_id, quantity=i.quantity) for i in payload.items],
            delivery_latitude=payload.latitude,
            delivery_longitude=payload.longitude,
            contact_phone=payload.contact_phone,
            note=payload.note,
            address_label=payload.address_label,
            address_details=payload.address_details,
            cashback_to_use=Decimal(str(payload.cashback_to_use or 0)),
            bottles_returned=int(payload.bottles_returned or 0),
            created_by_operator_id=int(user.id),
            payment_method=payload.payment_method,
            idempotency_key=payload.idempotency_key,
        ))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidOperationError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except DomainError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 3) Kuryerlar guruhiga xabar
    from aiogram.exceptions import TelegramAPIError
    try:
        msg_id = await notifier.dispatch_to_couriers_group(order)
        if msg_id is not None:
            await orders.attach_group_message(order.id, msg_id)
    except (TelegramAPIError, OSError) as e:
        log.warning("Operator buyurtmasi guruhiga yuborilmadi #%s: %s", order.id, e)
    try:
        await notifier.notify_couriers_new_order(order)
    except Exception as e:
        log.warning("Kuryerlarga DM bildirishnoma yuborilmadi #%s: %s", order.id, e)

    # 4) Mijozga DM (faqat has_started_bot=True bo'lsa — NotificationService o'zi tekshiradi)
    try:
        customer_msg_id = await notifier.upsert_customer_status_message(order)
        if customer_msg_id is not None:
            await orders.attach_customer_dm_message(order.id, customer_msg_id)
    except (TelegramAPIError, OSError) as e:
        log.warning("Mijoz status xabarini yuborib bo'lmadi #%s: %s", order.id, e)

    return OperatorOrderOut(
        id=order.id,
        display_number=order_display_number(order),
        status=order.status.name,
        total_amount=order.total_amount,
        customer_id=customer.id,
        customer_full_name=customer.full_name,
        customer_has_started_bot=bool(customer.has_started_bot),
        created_by_operator_id=int(user.id),
    )
