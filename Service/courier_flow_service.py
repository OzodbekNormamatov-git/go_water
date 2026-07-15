"""CourierFlowService — kuryer buyurtma oqimi orkestratori.

Claim va transitsiyalar (holat o'zgarishi + bildirishnomalar) shu yerda
markazlashgan: `OrderService` (DB, race-safe) + `NotificationService` (guruh
LOG'i + mijoz timeline'i). Web route'lar yupqa qoladi — bu DRY va testlanadigan.

Bildirishnomalar best-effort: ularning xatosi holat o'zgarishini orqaga
qaytarmaydi (DB allaqachon commit qilingan). Domain xatolari (`DomainError`)
caller'ga (route) ko'tariladi va u HTTP statusiga aylantiradi.
"""
from __future__ import annotations

import logging

from Service.notification_service import NotificationService
from Service.order_service import OrderService

log = logging.getLogger(__name__)


class CourierFlowService:
    def __init__(self, order_service: OrderService, notification_service: NotificationService) -> None:
        self._orders = order_service
        self._notify = notification_service

    # ---------------------- Bildirishnoma yordamchilari ----------------------

    async def _sync_group_log(self, order) -> None:
        try:
            await self._notify.update_group_log(order)
        except Exception as e:  # best-effort
            log.warning("Guruh LOG yangilanmadi #%s: %s", order.id, e)

    async def _sync_customer(self, order) -> None:
        try:
            mid = await self._notify.upsert_customer_status_message(order)
            if mid is not None:
                await self._orders.attach_customer_dm_message(order.id, mid)
        except Exception as e:
            log.warning("Mijoz timeline yangilanmadi #%s: %s", order.id, e)

    # ---------------------- Oqim ----------------------

    async def claim(self, courier, order_id: int):
        """Buyurtmani olish — race-safe (`claim_by_courier` SELECT FOR UPDATE)."""
        order = await self._orders.claim_by_courier(order_id, courier.telegram_id)
        await self._sync_group_log(order)
        await self._sync_customer(order)
        return order

    async def mark_delivering(self, courier, order_id: int):
        order = await self._orders.mark_delivering(order_id, courier.telegram_id)
        await self._sync_group_log(order)
        await self._sync_customer(order)
        return order

    async def mark_arrived(self, courier, order_id: int):
        order = await self._orders.mark_arrived(order_id, courier.telegram_id)
        await self._sync_group_log(order)
        await self._sync_customer(order)
        # Mijozga alohida "yetib keldi" push (e'tibor jalb qilish).
        try:
            aid = await self._notify.send_customer_arrived_alert(order)
            if aid is not None:
                await self._orders.attach_customer_arrived_message(order.id, aid)
        except Exception as e:
            log.info("ARRIVED alert yuborilmadi #%s: %s", order.id, e)
        return order

    async def set_bottles(self, courier, order_id: int, value: int):
        """Mijozdan olingan bo'sh idishlar soni (yetkazishdan oldin)."""
        return await self._orders.set_bottles_returned(order_id, courier.telegram_id, value)

    async def set_delivered_quantities(self, courier, order_id: int, quantities: dict[int, int]):
        """Kuryer yetkazgan haqiqiy dona sonini kiritadi — order moliyasi noldan
        qayta hisoblanadi. Guruh LOG'i va mijoz timeline'i yangi summa bilan
        yangilanadi (best-effort)."""
        order = await self._orders.set_delivered_quantities(order_id, courier.telegram_id, quantities)
        await self._sync_group_log(order)
        await self._sync_customer(order)
        return order

    async def set_payment_method(self, courier, order_id: int, method: str):
        """Kuryer yakuniy to'lov usulini (naqd/karta) tanlaydi. Guruh LOG'i
        yangilanadi (admin to'lov usulini ko'rib tursin)."""
        order = await self._orders.set_payment_method(order_id, courier.telegram_id, method)
        await self._sync_group_log(order)
        return order

    async def mark_delivered(self, courier, order_id: int):
        order = await self._orders.mark_delivered(order_id, courier.telegram_id)
        # Mijozning alohida "yetib keldi" xabarini o'chiramiz (bo'lsa).
        if order.customer_arrived_message_id:
            try:
                await self._notify.delete_customer_arrived_alert(order)
            except Exception:
                pass
            await self._orders.clear_customer_arrived_message(order.id)
        await self._sync_group_log(order)
        await self._sync_customer(order)
        return order
