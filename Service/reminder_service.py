"""ReminderService — avto "suv kerakmi?" eslatmasi (predictive reorder).

Kunlik fon job (Toshkent ertalab) har mijozning iste'mol tezligini hisoblab,
sikli tugayotganlarga DM yuboradi. Matematika `reminder_math.py` da (sof,
test qilinadi); bu yerda I/O orkestratsiya + anti-spam.

Anti-spam:
  * Global toggle (`AppSettings.reminders_enabled`) va per-mijoz opt-out
  * Ochiq (tugallanmagan) buyurtmasi bo'lsa — yubormaymiz
  * Oxirgi buyurtmadan keyin eng ko'pi `REMINDER_MAX_PER_ORDER` ta (keyin churn)
  * `k` hisoblagich due'ni har eslatmada bitta sikl oldinga suradi (kunlik spam yo'q)
  * Faqat ertalab (kunduzi) — kechqurun kuryersiz vaqtga tushmaydi
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from Data.unit_of_work import UnitOfWork
from Domain.constants import (
    BROADCAST_SEND_DELAY_SECONDS,
    REMINDER_MAX_PER_ORDER,
    REMINDER_SEND_HOUR_LOCAL,
)
from Domain.models.reminder import Reminder
from Service.reminder_math import due_datetime
from Service.timeutil import local_tz

log = logging.getLogger(__name__)


class ReminderService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        customer_bot: Bot,
        brand_name: str = "",
        webapp_url: Optional[str] = None,
    ) -> None:
        self._sf = session_factory
        self._bot = customer_bot
        self._brand = brand_name
        self._webapp_url = (webapp_url or "").rstrip("/") or None

    # ---------------------- Kunlik hisob ----------------------

    async def run_once(self) -> dict:
        """Bir martalik o'tish: due mijozlarni hisoblab, DM yuboradi. Stats qaytaradi."""
        async with UnitOfWork(self._sf) as uow:
            cfg = await uow.settings.get_or_create()
            if not cfg.reminders_enabled:
                return {"status": "disabled"}
            lead_days = max(0, int(cfg.reminder_lead_days or 0))
            candidates = [
                (u.id, u.telegram_id, u.full_name)
                for u in await uow.users.list_reminder_candidates()
            ]
            delivered = await uow.orders.all_delivered_for_cadence()
            open_set = await uow.orders.customers_with_open_order()
            sent_times = await uow.reminders.all_sent_times()

        # Tarixni mijoz bo'yicha guruhlaymiz (so'rovlar customer+sana bo'yicha tartibli).
        history: dict[int, list[tuple[datetime, int]]] = {}
        last_order_id: dict[int, int] = {}
        for cid, oid, dt, bottles in delivered:
            history.setdefault(cid, []).append((dt, bottles))
            last_order_id[cid] = oid
        rem_times: dict[int, list[datetime]] = {}
        for cid, t in sent_times:
            rem_times.setdefault(cid, []).append(t)

        tz = local_tz()
        today = datetime.now(tz).date()

        due: list[tuple] = []
        for cid, tg, name in candidates:
            if cid in open_set:
                continue
            hist = history.get(cid)
            if not hist:
                continue
            last_delivered = hist[-1][0]
            k = sum(1 for t in rem_times.get(cid, []) if t > last_delivered)
            if k >= REMINDER_MAX_PER_ORDER:
                continue
            res = due_datetime(hist, reminders_since_order=k)
            if res is None:
                continue
            due_utc, cycle = res
            due_local = due_utc.astimezone(tz).date()
            if today >= due_local - timedelta(days=lead_days):
                due.append((cid, tg, name, due_local, cycle, last_order_id.get(cid)))

        sent = failed = 0
        for cid, tg, name, due_local, cycle, anchor in due:
            try:
                await self._send_dm(int(tg), name, cycle)
                sent += 1
                async with UnitOfWork(self._sf) as uow:
                    await uow.reminders.add(Reminder(
                        customer_id=cid,
                        due_date=due_local,
                        cycle_days=Decimal(str(round(float(cycle), 2))),
                        anchor_order_id=anchor,
                    ))
            except TelegramForbiddenError:
                # Mijoz botni bloklagan — keyingi safar nomzod bo'lmasin.
                failed += 1
                async with UnitOfWork(self._sf) as uow:
                    u = await uow.users.get(cid)
                    if u is not None and u.has_started_bot:
                        u.has_started_bot = False
                        await uow.users.add(u)
            except (TelegramAPIError, OSError) as e:
                failed += 1
                log.warning("Eslatma yuborilmadi cid=%s: %s", cid, e)
            await asyncio.sleep(BROADCAST_SEND_DELAY_SECONDS)

        stats = {
            "status": "ok",
            "candidates": len(candidates),
            "due": len(due),
            "sent": sent,
            "failed": failed,
        }
        log.info("Avto-eslatma o'tishi: %s", stats)
        return stats

    async def _send_dm(self, telegram_id: int, name: str, cycle_days: float) -> None:
        days = int(round(float(cycle_days)))
        greeting = f", {name}" if name else ""
        text = (
            f"💧 Assalomu alaykum{greeting}!\n\n"
            f"Odatda har <b>~{days} kun</b>da suv buyurtma qilasiz — zaxirangiz "
            f"tugayotgan bo'lishi mumkin. Bugun suv kerakmi?\n\n"
            f"Bir bosishda buyurtma berishingiz mumkin 👇"
        )
        kb = None
        if self._webapp_url:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="💧 Buyurtma berish",
                    web_app=WebAppInfo(url=f"{self._webapp_url}/"),
                )
            ]])
        await self._bot.send_message(chat_id=telegram_id, text=text, reply_markup=kb)

    # ---------------------- Fon loop ----------------------

    async def run_forever(self) -> None:
        """Har kuni ertalab (REMINDER_SEND_HOUR_LOCAL) `run_once` ni chaqiradi.
        Restart-safe: keyingi ishga tushish vaqtini har safar qayta hisoblaydi."""
        while True:
            await asyncio.sleep(self._seconds_until_next_run())
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Avto-eslatma kunlik o'tishi xato bilan tugadi")

    def _seconds_until_next_run(self) -> float:
        tz = local_tz()
        now = datetime.now(tz)
        target = now.replace(
            hour=REMINDER_SEND_HOUR_LOCAL, minute=0, second=0, microsecond=0,
        )
        if now >= target:
            target = target + timedelta(days=1)
        return max(1.0, (target - now).total_seconds())
