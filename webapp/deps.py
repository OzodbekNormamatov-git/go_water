"""FastAPI dependencies — Service'larga va autentifikatsiyaga kirish.

`AppContainer` — main.py kompozitsiyaga ulanadi va `app.state.container` orqali
saqlanadi. Routerlar `Depends(...)` orqali kerakli service'larni oladi.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status

from Service.address_service import AddressService
from Service.analytics_service import AnalyticsService
from Service.broadcast_service import BroadcastService
from Service.cart_service import CartService
from Service.courier_flow_service import CourierFlowService
from Service.courier_service import CourierService
from Service.customer_lifecycle_service import CustomerLifecycleService
from Service.expense_service import ExpenseService
from Service.food_service import FoodService
from Service.geocode_service import GeocodeService
from Service.ledger_service import LedgerService
from Service.notification_service import NotificationService
from Service.operator_service import OperatorService
from Service.order_service import OrderService
from Service.promoter_service import PromoterService
from Service.settings_service import SettingsService
from Service.user_service import UserService
from webapp.auth import InitDataError, TelegramUser, verify_init_data

log = logging.getLogger(__name__)


@dataclass(slots=True)
class AppContainer:
    """main.py'da yaratiladi va FastAPI app.state.container ga biriktiriladi."""

    user_service: UserService
    food_service: FoodService
    order_service: OrderService
    notification_service: NotificationService
    cart_service: CartService
    courier_service: CourierService
    address_service: AddressService
    ledger_service: LedgerService
    analytics_service: AnalyticsService
    broadcast_service: BroadcastService
    settings_service: SettingsService
    geocode_service: GeocodeService
    courier_flow_service: CourierFlowService
    expense_service: ExpenseService
    lifecycle_service: CustomerLifecycleService
    operator_service: OperatorService
    promoter_service: PromoterService
    customer_bot_token: str
    admin_bot_token: str           # Admin Mini App initData verification uchun
    courier_bot_token: str         # Kuryer Mini App initData verification uchun
    brand_name: str
    # Admin rollari — .env whitelist (lockout'dan himoya: DB'ga bog'liq emas).
    # Operatorlar endi DB'da (operators jadvali) — env ro'yxati faqat seed.
    admin_telegram_ids: tuple[int, ...] = ()
    rate_limit_per_minute: int = 60


def _container(request: Request) -> AppContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server hali ishga tushmadi.",
        )
    return container


def get_user_service(c: AppContainer = Depends(_container)) -> UserService:
    return c.user_service


def get_food_service(c: AppContainer = Depends(_container)) -> FoodService:
    return c.food_service


def get_order_service(c: AppContainer = Depends(_container)) -> OrderService:
    return c.order_service


def get_notification_service(c: AppContainer = Depends(_container)) -> NotificationService:
    return c.notification_service


def get_cart_service(c: AppContainer = Depends(_container)) -> CartService:
    return c.cart_service


def get_courier_service(c: AppContainer = Depends(_container)) -> CourierService:
    return c.courier_service


def get_address_service(c: AppContainer = Depends(_container)) -> AddressService:
    return c.address_service


def get_ledger_service(c: AppContainer = Depends(_container)) -> LedgerService:
    return c.ledger_service


def get_analytics_service(c: AppContainer = Depends(_container)) -> AnalyticsService:
    return c.analytics_service


def get_broadcast_service(c: AppContainer = Depends(_container)) -> BroadcastService:
    return c.broadcast_service


def get_settings_service(c: AppContainer = Depends(_container)) -> SettingsService:
    return c.settings_service


def get_brand_name(c: AppContainer = Depends(_container)) -> str:
    return c.brand_name


def get_geocode_service(c: AppContainer = Depends(_container)) -> GeocodeService:
    return c.geocode_service


def get_courier_flow_service(c: AppContainer = Depends(_container)) -> CourierFlowService:
    return c.courier_flow_service


def get_expense_service(c: AppContainer = Depends(_container)) -> ExpenseService:
    return c.expense_service


def get_lifecycle_service(c: AppContainer = Depends(_container)) -> CustomerLifecycleService:
    return c.lifecycle_service


def get_operator_service(c: AppContainer = Depends(_container)) -> OperatorService:
    return c.operator_service


def get_promoter_service(c: AppContainer = Depends(_container)) -> PromoterService:
    return c.promoter_service


# ---------------------- Telegram Mini App auth ----------------------
# `Authorization: tma <initData>` — Telegram'ning rasmiy tavsiyasi.
# Frontend `WebApp.initData` ni xuddi shu ko'rinishda yuboradi.

_AUTH_PREFIX = "tma "


def telegram_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    c: AppContainer = Depends(_container),
) -> TelegramUser:
    """Joriy so'rovning Telegram foydalanuvchisini qaytaradi (HMAC tekshirilgan).

    Header formati: `Authorization: tma <initData query string>`.
    """
    if not authorization or not authorization.lower().startswith(_AUTH_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header yo'q yoki noto'g'ri (kutilgan: 'tma <initData>').",
            headers={"WWW-Authenticate": 'tma realm="webapp"'},
        )
    init_data = authorization[len(_AUTH_PREFIX):].strip()
    try:
        return verify_init_data(init_data, bot_token=c.customer_bot_token)
    except InitDataError:
        # 401 — odatda eski sessiya. INFO darajasida (spam emas).
        log.info("InitData rad etildi ip=%s", request.client.host if request.client else "?")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Avtorizatsiya muvaffaqiyatsiz. Mini App'ni qaytadan oching.",
            headers={"WWW-Authenticate": 'tma realm="webapp"'},
        )


def courier_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    c: AppContainer = Depends(_container),
) -> TelegramUser:
    """Kuryer Mini App initData (courier_bot tokeni bilan imzolangan)."""
    if not authorization or not authorization.lower().startswith(_AUTH_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header yo'q (kutilgan: 'tma <initData>').",
            headers={"WWW-Authenticate": 'tma realm="courier"'},
        )
    init_data = authorization[len(_AUTH_PREFIX):].strip()
    try:
        return verify_init_data(init_data, bot_token=c.courier_bot_token)
    except InitDataError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Avtorizatsiya muvaffaqiyatsiz. Ilovani qaytadan oching.",
            headers={"WWW-Authenticate": 'tma realm="courier"'},
        )


async def current_courier(
    user: TelegramUser = Depends(courier_user),
    couriers=Depends(get_courier_service),
):
    """Joriy kuryerni qaytaradi — ro'yxatda + arxivlanmagan + AKTIV bo'lishi shart."""
    courier = await couriers.get_by_telegram_id(user.id)
    if courier is None or getattr(courier, "is_deleted", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Siz kuryer sifatida ro'yxatda yo'qsiz. Avval kuryer botiga /start yuboring.",
        )
    if not courier.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hisobingiz hali aktivlashtirilmagan. Admin bilan bog'laning.",
        )
    return courier


def any_telegram_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    c: AppContainer = Depends(_container),
) -> TelegramUser:
    """Mijoz YOKI admin Mini App'idan kelgan initData'ni qabul qiladi.

    Geocoding kabi umumiy (ikkala panelga ham kerak) endpointlar uchun — initData
    customer_bot yoki admin_bot tokeni bilan imzolangan bo'lsa, qabul qilamiz."""
    if not authorization or not authorization.lower().startswith(_AUTH_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header yo'q (kutilgan: 'tma <initData>').",
            headers={"WWW-Authenticate": 'tma realm="webapp"'},
        )
    init_data = authorization[len(_AUTH_PREFIX):].strip()
    for token in (c.customer_bot_token, c.admin_bot_token):
        try:
            return verify_init_data(init_data, bot_token=token)
        except InitDataError:
            continue
    log.info("any_telegram_user: initData rad etildi")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Avtorizatsiya muvaffaqiyatsiz. Mini App'ni qaytadan oching.",
        headers={"WWW-Authenticate": 'tma realm="webapp"'},
    )
