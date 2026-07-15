"""Buyurtmalar — yaratish va tarix.

Yaratilgan buyurtma uchun bot orqali yuboriladigan barcha xabarlar
(kuryerlar guruhi, adminlar) Mini App'dan ham ishga tushadi —
biz `notification_service` ni xuddi botdagi kabi chaqiramiz.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from Domain.enums import PaymentMethod
from Service.cart_service import CartService
from Service.exceptions import (
    DomainError,
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from Service.notification_service import NotificationService
from Service.order_display import order_display_number
from Service.order_service import (
    CartItem,
    NewOrderInput,
    OrderService,
)
from Service.user_service import UserService
from webapp.auth import TelegramUser
from webapp.deps import (
    get_cart_service,
    get_notification_service,
    get_order_service,
    get_user_service,
    telegram_user,
)
from webapp.pagination import Page
from webapp.schemas import (
    CourierOut,
    OrderCreateIn,
    OrderDetailOut,
    OrderItemOut,
    OrderOut,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def _common_fields(order) -> dict:
    """OrderOut va OrderDetailOut o'rtasidagi umumiy field'lar."""
    return {
        "id": order.id,
        "daily_number": getattr(order, "daily_number", None),
        "display_number": order_display_number(order),
        "status": order.status.name,
        "status_label": order.status.label_uz,
        "total_amount": order.total_amount,
        "contact_phone": order.contact_phone,
        "note": order.note or "",
        "created_at": _iso(order.created_at),
        "items": [
            OrderItemOut(
                food_id=it.food_id,
                food_name=it.food_name,
                unit_price=it.unit_price,
                # quantity — AMALDAGI (yetkazilgan) dona; ordered_quantity — asl.
                quantity=int(it.effective_quantity),
                ordered_quantity=int(it.quantity),
            )
            for it in (order.items or [])
        ],
        "items_total": Decimal(order.items_total or 0),
        "cashback_used": Decimal(order.cashback_used or 0),
        "cashback_earned": Decimal(order.cashback_earned or 0),
        "bottles_issued": int(order.bottles_issued or 0),
        "bottles_returned": int(order.bottles_returned or 0),
        "address_label": getattr(order, "address_label", "") or "",
        "address_details": getattr(order, "address_details", "") or "",
        "payment_method": _payment_method_of(order),
        "payment_method_label": _payment_label_of(order),
    }


def _payment_method_of(order) -> str:
    return str(getattr(order, "payment_method", "cash") or "cash")


def _payment_label_of(order) -> str:
    try:
        pm = PaymentMethod(_payment_method_of(order))
    except ValueError:
        return "Naqd"
    return f"{pm.emoji} {pm.label_uz}"


def _to_out(order) -> OrderOut:
    return OrderOut(**_common_fields(order))


def _to_detail(order) -> OrderDetailOut:
    courier = None
    if order.courier is not None:
        courier = CourierOut(
            full_name=order.courier.full_name,
            username=order.courier.username,
            phone_number=order.courier.phone_number,
        )
    return OrderDetailOut(
        **_common_fields(order),
        courier=courier,
        latitude=float(order.delivery_latitude),
        longitude=float(order.delivery_longitude),
        map_url=f"https://maps.google.com/?q={order.delivery_latitude},{order.delivery_longitude}",
        accepted_at=_iso(order.accepted_at),
        delivering_at=_iso(getattr(order, "delivering_at", None)),
        arrived_at=_iso(getattr(order, "arrived_at", None)),
        delivered_at=_iso(order.delivered_at),
        cancelled_at=_iso(order.cancelled_at),
    )


@router.get("", response_model=Page[OrderOut])
async def list_my_orders(
    user: TelegramUser = Depends(telegram_user),
    orders: OrderService = Depends(get_order_service),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[OrderOut]:
    items = await orders.list_for_customer(user.id, limit=limit, offset=offset)
    total = await orders.count_for_customer(user.id)
    return Page[OrderOut](
        items=[_to_out(o) for o in items],
        total=total, limit=limit, offset=offset,
    )


@router.get("/{order_id}", response_model=OrderDetailOut)
async def get_order_detail(
    order_id: int,
    user: TelegramUser = Depends(telegram_user),
    orders: OrderService = Depends(get_order_service),
    users: UserService = Depends(get_user_service),
) -> OrderDetailOut:
    me = await users.get_by_telegram_id(user.id)
    if me is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ro'yxatdan o'tmagansiz.")
    try:
        order = await orders.get(order_id)
    except EntityNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buyurtma topilmadi.")
    if order.customer_id != me.id:
        # Boshqa odamning buyurtmasini ko'rib bo'lmaydi.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sizning buyurtmangiz emas.")
    return _to_detail(order)


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreateIn,
    user: TelegramUser = Depends(telegram_user),
    orders: OrderService = Depends(get_order_service),
    notifier: NotificationService = Depends(get_notification_service),
    carts: CartService = Depends(get_cart_service),
) -> OrderOut:
    try:
        order = await orders.create_order(
            NewOrderInput(
                customer_telegram_id=user.id,
                items=[
                    CartItem(food_id=i.food_id, quantity=i.quantity)
                    for i in payload.items
                ],
                delivery_latitude=payload.latitude,
                delivery_longitude=payload.longitude,
                contact_phone=payload.contact_phone,
                note=payload.note,
                idempotency_key=payload.idempotency_key,
                address_label=payload.address_label,
                address_details=payload.address_details,
                cashback_to_use=Decimal(str(payload.cashback_to_use or 0)),
                bottles_returned=int(payload.bottles_returned or 0),
                payment_method=payload.payment_method,
            )
        )
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except InvalidOperationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except DomainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Server-side cart'ni tozalaymiz — buyurtma yaratilgani uchun. Idempotency
    # bo'lsa ham bu OK: ikkinchi marta tozalash no-op.
    try:
        await carts.clear(user.id)
    except Exception as e:  # cart tozalash kritik emas
        log.warning("Cart tozalanmadi (order #%s): %s", order.id, e)

    # Notifikatsiyalar — best-effort, asosiy javobni bloklamaymiz.
    from aiogram.exceptions import TelegramAPIError
    try:
        msg_id = await notifier.dispatch_to_couriers_group(order)
        if msg_id is not None:
            await orders.attach_group_message(order.id, msg_id)
    except (TelegramAPIError, OSError) as e:
        log.warning("Buyurtmani kuryerlar guruhiga yuborib bo'lmadi #%s: %s", order.id, e)
    try:
        await notifier.notify_couriers_new_order(order)
    except Exception as e:
        log.warning("Kuryerlarga DM bildirishnoma yuborilmadi #%s: %s", order.id, e)
    # Mijoz DM da bitta "holat lentasi" xabari — keyingi statuslar shu xabarni edit qiladi.
    try:
        customer_msg_id = await notifier.upsert_customer_status_message(order)
        if customer_msg_id is not None:
            await orders.attach_customer_dm_message(order.id, customer_msg_id)
    except (TelegramAPIError, OSError) as e:
        log.warning("Mijoz status xabarini yuborib bo'lmadi #%s: %s", order.id, e)

    return _to_out(order)
