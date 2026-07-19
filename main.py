"""
Delivery bot — kompozitsiya ildizi (composition root).

Tier'lar quyidagicha ulanadi:

    Bots (presentation)            WebApp (presentation)
        ↓ uses                        ↓ uses
    Service (application + business rules)
        ↓ uses
    Data (repositories, UnitOfWork, async SQLAlchemy)
        ↓ maps
    Domain (entities, enums)

3 ta bot va FastAPI Mini App bitta jarayonda asyncio.gather orqali parallel ishlaydi.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from Bots.admin import build_admin_dispatcher, make_admin_bot
from Bots.courier import build_courier_dispatcher, make_courier_bot
from Bots.customer.bot import build_customer_dispatcher, make_customer_bot
from Data.database import Database
from Service.address_service import AddressService
from Service.analytics_service import AnalyticsService
from Service.broadcast_service import BroadcastService
from Service.cart_service import CartService
from Service.courier_service import CourierService
from Service.courier_flow_service import CourierFlowService
from Service.customer_lifecycle_service import CustomerLifecycleService
from Service.expense_service import ExpenseService
from Service.food_service import FoodService
from Service.geocode_service import GeocodeService
from Service.ledger_service import LedgerService
from Service.notification_service import NotificationService
from Service.operator_service import OperatorService
from Service.promoter_service import PromoterService
from Service.order_service import OrderService
from Service.reminder_service import ReminderService
from Service.report_service import ReportService
from Service.settings_service import SettingsService
from Service.user_service import UserService
from config import get_settings
from webapp.app import create_app
from webapp.deps import AppContainer

log = logging.getLogger("delivery_bot")


def _setup_logging(level: str) -> None:
    """Konsol + fayl (logs/bot.log, 5MB × 5 rotatsiya).

    Avval faqat stderr edi — 500 xatolarning traceback'lari terminal yopilishi
    bilan yo'qolardi ("rasxod qo'shilmayapti" bugini topish imkonsiz edi).
    Endi har qanday xato logs/bot.log'da saqlanadi.
    """
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level.upper())

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        log_dir = Path(__file__).resolve().parent / "logs"
        log_dir.mkdir(exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "bot.log", maxBytes=5 * 1024 * 1024, backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError as e:  # disk to'la / ruxsat yo'q — konsol bilan davom etamiz
        root.warning("Log fayl ochilmadi (%s) — faqat konsol logging", e)


async def _run() -> None:
    settings = get_settings()

    _setup_logging(settings.log_level)

    db = Database(settings.database_url, echo=False)
    await db.create_all()
    log.info("DB ready: %s", settings.database_url)

    # Service layer (singletons) — har bir service session_factory'ni ushlab turadi
    user_service = UserService(db.session_factory)
    courier_service = CourierService(db.session_factory)
    # Operatorlar FAQAT DB'dan (operators jadvali): admin botga /start →
    # noaktiv qator → admin panel "Operatorlar"dan aktivlashtiradi.
    # .env seed YO'Q — eski OPERATOR_TELEGRAM_IDS butunlay bekor qilingan.
    operator_service = OperatorService(db.session_factory)
    # Promouterlar (uyma-uy ishchilar) — faqat DB'da; admin panelidan yaratiladi.
    # Bot/login yo'q: ishchi tizimga kirmaydi, u faqat promokod egasi.
    promoter_service = PromoterService(db.session_factory)
    food_service = FoodService(db.session_factory)
    order_service = OrderService(db.session_factory)
    cart_service = CartService(db.session_factory)
    address_service = AddressService(db.session_factory)
    ledger_service = LedgerService(db.session_factory)
    expense_service = ExpenseService(db.session_factory)
    # Analytics rasxod servisiga tayanadi — sof foyda bloki (COGS + rasxodlar).
    analytics_service = AnalyticsService(db.session_factory, expense_service=expense_service)
    settings_service = SettingsService(db.session_factory)
    # Aqlli eslatma — operator "suv olish vaqti kelgan" mijozlar ro'yxati.
    lifecycle_service = CustomerLifecycleService(db.session_factory)
    geocode_service = GeocodeService(
        search_url=settings.geocode_search_url,
        reverse_url=settings.geocode_reverse_url,
        user_agent=settings.geocode_user_agent,
        bias_lat=settings.geocode_bias_lat,
        bias_lon=settings.geocode_bias_lon,
    )

    # Botlar
    customer_bot = make_customer_bot(settings.customer_bot_token)
    admin_bot = make_admin_bot(settings.admin_bot_token)
    courier_bot = make_courier_bot(settings.courier_bot_token)

    # Broadcast — customer_bot orqali yuboradi (DM mijozlarga).
    broadcast_service = BroadcastService(db.session_factory, customer_bot=customer_bot)

    # Avto-eslatma ("suv kerakmi?") — kunlik fon job, customer_bot orqali DM.
    reminder_service = ReminderService(
        db.session_factory,
        customer_bot=customer_bot,
        brand_name=settings.brand_name,
        webapp_url=settings.webapp_public_url or None,
    )

    notifier = NotificationService(
        courier_bot=courier_bot,
        customer_bot=customer_bot,
        admin_bot=admin_bot,
        courier_group_chat_id=settings.courier_group_chat_id,
        admin_telegram_ids=settings.admin_ids,
        brand_name=settings.brand_name,
        session_factory=db.session_factory,
        webapp_url=settings.webapp_public_url or None,
    )

    # Kuryer oqimi orkestratori — web route'lar yupqa qoladi (best practice).
    courier_flow_service = CourierFlowService(order_service, notifier)

    customer_dp = build_customer_dispatcher(
        user_service=user_service,
        food_service=food_service,
        order_service=order_service,
        notification_service=notifier,
        brand_name=settings.brand_name,
        webapp_url=settings.webapp_public_url or None,
    )
    admin_dp = build_admin_dispatcher(
        food_service=food_service,
        order_service=order_service,
        courier_service=courier_service,
        user_service=user_service,
        notification_service=notifier,
        admin_telegram_ids=settings.admin_ids,
        operator_service=operator_service,
        webapp_public_url=settings.webapp_public_url or None,
    )
    courier_dp = build_courier_dispatcher(
        courier_service=courier_service,
        courier_group_chat_id=settings.courier_group_chat_id,
    )

    # ===== Menu Button (chat input chap pastdagi yumaloq tugma) =====
    # Bu setChatMenuButton orqali default sifatida o'rnatiladi va barcha
    # adminlar/mijozlar uchun har doim ko'rinadi — reply keyboard'siz ham
    # ishlaydi. Reply keyboard tugmasi muammoli bo'lsa, bu zaxira yo'l.
    if settings.webapp_public_url:
        from aiogram.types import MenuButtonWebApp, WebAppInfo as _WebAppInfo
        public_url = settings.webapp_public_url.rstrip("/")
        try:
            await admin_bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
                text="Admin paneli",
                web_app=_WebAppInfo(url=f"{public_url}/admin/"),
            ))
            log.info("Admin bot menu button -> %s/admin/", public_url)
        except Exception as e:
            log.warning("Admin bot menu button setup failed: %s", e)
        try:
            await customer_bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
                text="Buyurtma",
                web_app=_WebAppInfo(url=f"{public_url}/"),
            ))
            log.info("Customer bot menu button -> %s/", public_url)
        except Exception as e:
            log.warning("Customer bot menu button setup failed: %s", e)
        try:
            await courier_bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
                text="Buyurtmalar",
                web_app=_WebAppInfo(url=f"{public_url}/courier/"),
            ))
            log.info("Courier bot menu button -> %s/courier/", public_url)
        except Exception as e:
            log.warning("Courier bot menu button setup failed: %s", e)

    # Excel hisobot (admin panel tugmasi) — .xlsx qurib admin botga DM qiladi.
    # expense_service — rasxodlar varag'i + P&L (sof foyda) bloki uchun.
    report_service = ReportService(
        db.session_factory, admin_bot=admin_bot, expense_service=expense_service,
    )

    # FastAPI Mini App
    container = AppContainer(
        promoter_service=promoter_service,
        user_service=user_service,
        food_service=food_service,
        order_service=order_service,
        notification_service=notifier,
        cart_service=cart_service,
        courier_service=courier_service,
        address_service=address_service,
        ledger_service=ledger_service,
        analytics_service=analytics_service,
        broadcast_service=broadcast_service,
        settings_service=settings_service,
        geocode_service=geocode_service,
        courier_flow_service=courier_flow_service,
        expense_service=expense_service,
        lifecycle_service=lifecycle_service,
        operator_service=operator_service,
        report_service=report_service,
        customer_bot_token=settings.customer_bot_token,
        admin_bot_token=settings.admin_bot_token,
        courier_bot_token=settings.courier_bot_token,
        admin_telegram_ids=tuple(settings.admin_ids),
        brand_name=settings.brand_name,
        rate_limit_per_minute=settings.rate_limit_per_minute,
    )
    fastapi_app = create_app(container=container, cors_origins=settings.cors_origins)
    uvicorn_config = uvicorn.Config(
        fastapi_app,
        host=settings.webapp_host,
        port=settings.webapp_port,
        log_level=settings.log_level.lower(),
        loop="asyncio",
        # access logni o'chiramiz: bizning logger format'imizdan farqli, shovqin qiladi.
        access_log=False,
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)

    log.info(
        "Starting 3 bots + Mini App on http://%s:%s …",
        settings.webapp_host, settings.webapp_port,
    )
    if settings.webapp_public_url:
        log.info("Customer Mini App URL:  %s/", settings.webapp_public_url.rstrip("/"))
        log.info("Admin Mini App URL:     %s/admin/", settings.webapp_public_url.rstrip("/"))
        log.info(
            "MUHIM: @BotFather'da har 2 botning Mini App / setdomain'i shu host bilan "
            "moslashtirilgan bo'lishi shart, aks holda Telegram WebApp tugmasini "
            "to'g'ri ochmaydi. Reply keyboard'ni yangilash uchun botda /start yuboring."
        )
    else:
        log.warning(
            "WEBAPP_PUBLIC_URL .env'da bo'sh — Mini App tugmalari bot keyboard'ida "
            "ko'rinmaydi. ngrok yoki HTTPS domen URL'ni qo'shing."
        )

    async def _supervised(name: str, coro_fn):
        """Bitta task crash bo'lsa qolganlari ishlashda davom etsin.

        Polling qisqa muddatli xatoliklarda (network) avtomatik qayta urinadi.
        Uvicorn `sys.exit(1)` chiqarsa, u `SystemExit` (BaseException) — biz
        uni ham tutib, qolgan botlar to'xtab qolmasligi uchun.
        """
        try:
            await coro_fn()
        except asyncio.CancelledError:
            raise
        except SystemExit as e:
            # Uvicorn port band bo'lsa sys.exit(1) chaqiradi — diagnostika beraylik.
            log.error(
                "Task '%s' SystemExit(%s) bilan to'xtadi. "
                "Agar webapp bo'lsa — port (%s) band bo'lishi mumkin. "
                "Eski 'python main.py' jarayonlarini o'chirib, qaytadan urinib ko'ring.",
                name, e.code, settings.webapp_port,
            )
        except Exception:
            log.exception("Task '%s' halokatli to'xtadi", name)

    try:
        await asyncio.gather(
            _supervised("customer_bot", lambda: customer_dp.start_polling(customer_bot)),
            _supervised("admin_bot",    lambda: admin_dp.start_polling(admin_bot)),
            _supervised("courier_bot",  lambda: courier_dp.start_polling(courier_bot)),
            _supervised("webapp",       lambda: uvicorn_server.serve()),
            _supervised("reminders",    lambda: reminder_service.run_forever()),
        )
    finally:
        await asyncio.gather(
            customer_bot.session.close(),
            admin_bot.session.close(),
            courier_bot.session.close(),
            return_exceptions=True,
        )
        await db.dispose()


def main() -> None:
    try:
        asyncio.run(_run())
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutdown by signal")
        sys.exit(0)


if __name__ == "__main__":
    main()
