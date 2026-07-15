"""High-level NotificationService — yuborish/edit orkestratsiyasi.

Tashqi API eski versiyaga moslashgan (callers o'zgartirmasdan ishlaydi).
Formatter sof funktiyalar `formatters.py` da — alohida testlash mumkin.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Iterable, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from Domain.models.order import Order
from Service.order_display import order_display_number
from Service.notifications.formatters import (
    format_customer_arrived,
    format_customer_timeline,
    format_group_log,
)

log = logging.getLogger(__name__)


class NotificationService:
    """Telegram orqali xabar yuborish/tahrirlashning kompozit qatlami.

    Bot'lar va WebApp shu yagona service'ni chaqiradi.
    """

    def __init__(
        self,
        *,
        courier_bot: Bot,
        customer_bot: Bot,
        admin_bot: Bot,
        courier_group_chat_id: int,
        admin_telegram_ids: Iterable[int],
        brand_name: str,
        session_factory=None,
        webapp_url: Optional[str] = None,
    ) -> None:
        self._courier_bot = courier_bot
        self._customer_bot = customer_bot
        self._admin_bot = admin_bot
        self._courier_group_chat_id = courier_group_chat_id
        self._admin_telegram_ids = list(admin_telegram_ids)
        self._brand_name = brand_name
        # Kuryer web app DM bildirishnomasi uchun (aktiv kuryerlarni topish + tugma URL).
        self._session_factory = session_factory
        self._webapp_url = (webapp_url or "").rstrip("/") or None

    # ---------------------- Couriers group ----------------------

    async def dispatch_to_couriers_group(self, order: Order) -> Optional[int]:
        """Kuryerlar guruhiga buyurtmani yozadi — endi faqat ADMIN LOG (tugmasiz).

        Kuryerlar claim qilmaydi (claim web ilovada). Bu xabar buyurtma holati
        o'zgargan sari `update_group_log` orqali tahrirlanib boradi."""
        try:
            msg = await self._courier_bot.send_message(
                chat_id=self._courier_group_chat_id,
                text=format_group_log(order),
                reply_markup=None,
                disable_web_page_preview=True,
            )
        except TelegramAPIError as e:
            log.error(
                "Kuryerlar guruhiga xabar yuborib bo'lmadi (chat_id=%s, order=%s): %s",
                self._courier_group_chat_id, order.id, e,
            )
            await self._alert_admins(
                f"⚠️ <b>Buyurtma {order_display_number(order)}</b> kuryerlar guruhiga yuborilmadi!\n\n"
                f"Sabab: <code>{e}</code>\n\n"
                f"Tekshiring: COURIER_GROUP_CHAT_ID to'g'rimi va kuryer boti "
                f"guruhga qo'shilganmi (admin sifatida)."
            )
            return None
        try:
            await self._courier_bot.send_location(
                chat_id=self._courier_group_chat_id,
                latitude=float(order.delivery_latitude),
                longitude=float(order.delivery_longitude),
                reply_to_message_id=msg.message_id,
            )
        except TelegramAPIError as e:
            log.warning("Guruhga lokatsiya yuborilmadi #%s: %s", order.id, e)
        return msg.message_id

    async def notify_couriers_new_order(self, order: Order) -> None:
        """Har aktiv kuryerga DM — yangi buyurtma, web app'ni ochuvchi tugma bilan.

        Guruhga yuborishga QO'SHIMCHA: kuryer ilovani yopiq bo'lsa ham biladi.
        Best-effort — bloklagan/yetib bo'lmaydigan kuryerlar jim o'tkaziladi."""
        if self._session_factory is None:
            return
        from Data.unit_of_work import UnitOfWork
        try:
            async with UnitOfWork(self._session_factory) as uow:
                tg_ids = await uow.couriers.list_active_started_telegram_ids()
        except Exception as e:  # DB muammosi bildirishnomani to'xtatmasin
            log.warning("Aktiv kuryerlar ro'yxatini olishda xato: %s", e)
            return
        if not tg_ids:
            return
        from Bots.common import fmt_money
        addr = (order.address_details or "").strip()
        text = (
            f"🆕 <b>Yangi buyurtma {order_display_number(order)}</b>\n"
            f"💰 {fmt_money(order.total_amount)}"
            + (f"\n📍 {addr}" if addr else "")
            + "\n\nKim birinchi olsa — o'shaniki. Olish uchun ilovani oching 👇"
        )
        kb = None
        if self._webapp_url:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="📋 Buyurtmani olish",
                    web_app=WebAppInfo(url=f"{self._webapp_url}/courier/"),
                )
            ]])
        for tg in tg_ids:
            try:
                await self._courier_bot.send_message(chat_id=int(tg), text=text, reply_markup=kb)
            except TelegramForbiddenError:
                pass  # kuryer botni bloklagan — jim o'tkazamiz
            except TelegramAPIError as e:
                log.debug("Kuryerga DM yuborilmadi tg=%s: %s", tg, e)
            await asyncio.sleep(0.05)  # Telegram rate-limit

    async def update_group_log(self, order: Order) -> None:
        """Guruhdagi (admin LOG) xabarni buyurtma joriy holatiga moslab tahrirlaydi.

        Yangi → olindi (kim) → yo'lda → yetib bordi → yetkazildi. Tugma yo'q —
        kuryerlar ishni web ilovada qiladi; guruh faqat admin kuzatuvi uchun."""
        if not order.group_message_id:
            return
        try:
            await self._courier_bot.edit_message_text(
                chat_id=self._courier_group_chat_id,
                message_id=order.group_message_id,
                text=format_group_log(order),
                reply_markup=None,
                disable_web_page_preview=True,
            )
        except TelegramAPIError as e:
            log.warning("Guruh log xabarini tahrirlab bo'lmadi #%s: %s", order.id, e)

    # ---------------------- Customer DM (timeline) ----------------------

    @staticmethod
    def _customer_can_receive_dm(order: Order) -> bool:
        """Mijozga DM yuborish mumkinmi?

        Quyidagi hollarda yo'q:
          * `customer` relationi yuklanmagan (orphan order)
          * `has_started_bot=False` (operator yaratgan "guest" mijoz yoki
            ilk marta bot bilan ishlamagan mavjud mijoz)
          * `telegram_id` manfiy (sintetik ID — bot bilan ishlamaydi)

        Bu tekshiruv Telegram API'ga ortiqcha urinishni va log noise'ni
        oldini oladi (`TelegramForbiddenError` baribir tushardi).
        """
        customer = getattr(order, "customer", None)
        if customer is None:
            return False
        if not getattr(customer, "has_started_bot", False):
            return False
        tg_id = int(getattr(customer, "telegram_id", 0) or 0)
        if tg_id <= 0:
            return False
        return True

    async def upsert_customer_status_message(self, order: Order) -> Optional[int]:
        """Mijozga yagona "holat lentasi" xabarini yuboradi yoki tahrirlaydi.

        Mijoz botda /start bosmagan bo'lsa (operator yaratgan "guest" mijoz) —
        silent skip, hech qanday API chaqiruv qilmaymiz.

        Returns:
            Yangi yuborilgan bo'lsa msg_id (caller saqlashi kerak), edit yoki skip — None.
        """
        if not self._customer_can_receive_dm(order):
            return None
        tg_id = order.customer.telegram_id
        body = format_customer_timeline(order, self._brand_name)

        if order.customer_dm_message_id:
            try:
                await self._customer_bot.edit_message_text(
                    chat_id=tg_id,
                    message_id=order.customer_dm_message_id,
                    text=body,
                    disable_web_page_preview=True,
                )
                return None
            except TelegramAPIError as e:
                if "message is not modified" in str(e).lower():
                    return None
                log.info(
                    "Mijoz status xabarini edit qilib bo'lmadi (order=%s): %s — yangi xabar yuboriladi.",
                    order.id, e,
                )

        try:
            msg = await self._customer_bot.send_message(
                chat_id=tg_id, text=body, disable_web_page_preview=True,
            )
            return msg.message_id
        except TelegramAPIError as e:
            log.warning("Mijozga status xabarini yuborib bo'lmadi (order=%s, tg=%s): %s", order.id, tg_id, e)
            return None

    # ---------------------- Customer ARRIVED alert (alohida xabar) ----------------------

    async def send_customer_arrived_alert(self, order: Order) -> Optional[int]:
        """Mijozga "buyurtmangiz yetib keldi!" alohida xabar yuboradi.

        Asosiy timeline xabariga TEGMAYDI — bu yangi, qisqa, e'tiborni jalb qiluvchi
        bildirishnoma. Mijoz botda /start bosmagan bo'lsa silent skip.
        Idempotent: agar shu order uchun avval yuborilgan bo'lsa, qaytadan yubormaydi.
        """
        if order.customer_arrived_message_id:
            return None
        if not self._customer_can_receive_dm(order):
            return None
        tg_id = order.customer.telegram_id
        try:
            msg = await self._customer_bot.send_message(
                chat_id=tg_id,
                text=format_customer_arrived(order),
                disable_web_page_preview=True,
            )
            return msg.message_id
        except TelegramAPIError as e:
            log.warning(
                "Mijozga 'yetib keldi' xabarini yuborib bo'lmadi (order=%s, tg=%s): %s",
                order.id, tg_id, e,
            )
            return None

    async def delete_customer_arrived_alert(self, order: Order) -> None:
        """ARRIVED bildirishnomasini o'chiradi (DELIVERED bo'lganda chaqiriladi).

        Telegram xato qaytarsa (xabar topilmadi va h.k.) — silent o'tamiz.
        """
        if not order.customer_arrived_message_id:
            return
        try:
            tg_id = order.customer.telegram_id
        except AttributeError:
            return
        try:
            await self._customer_bot.delete_message(
                chat_id=tg_id, message_id=order.customer_arrived_message_id,
            )
        except TelegramAPIError as e:
            log.info(
                "ARRIVED xabarini o'chirib bo'lmadi (order=%s) — Telegram: %s. "
                "Davom etamiz (mijoz qo'lda o'chirgan bo'lishi mumkin).",
                order.id, e,
            )

    # ---------------------- Admin alerts ----------------------

    async def _alert_admins(self, text: str) -> None:
        for admin_id in self._admin_telegram_ids:
            try:
                await self._admin_bot.send_message(chat_id=admin_id, text=text)
            except TelegramAPIError as e:
                log.warning(
                    "Adminga ogohlantirish yuborib bo'lmadi tg=%s: %s "
                    "(admin admin_botga /start bosganmi?)", admin_id, e,
                )
