"""CustomerLifecycleService — mijoz qayta-buyurtma segmentatsiyasi (Aqlli eslatma).

"Aqlli eslatma" — suv olish vaqti kelgan mijozlarni aniqlaydigan tizim.
Bitta hisoblash — ikki iste'molchi:
  * Operator web-bo'limi (Aqlli eslatma paneli): kimga qo'ng'iroq qilish kerak —
    DUE/OVERDUE/CHURNED ro'yxati, kechikish bo'yicha tartiblangan.
  * (Kelajakda) DM eslatma oqimi ham shu segmentlarga tayanishi mumkin —
    matematika allaqachon umumiy (`reminder_math`).

Segmentlar (faqat kamida 1 ta DELIVERED buyurtmasi borlar uchun):
  ACTIVE   — sikl bo'yicha hali vaqti kelmagan, yoki hozir ochiq buyurtmasi bor
  DUE      — reorder oynasi yetdi (due − lead_days <= bugun <= due)
  OVERDUE  — vaqtidan o'tdi (due < bugun <= due + churn_after) — churn xavfi;
             "1 marta olib to'xtagan" mijozlar odatda shu yerda ushlanadi
  CHURNED  — uzoq qaytmagan (bugun > due + churn_after) — win-back ro'yxati

MUHIM FARQ: DM eslatma (`ReminderService`) har yuborilgan eslatma bilan due'ni
bitta sikl OLDINGA suradi (anti-spam). Aqlli eslatma paneli esa BAZAVIY due
(k=0) dan hisoblaydi — operator mijozning haqiqiy kechikishini ko'rsin, DM
tarixiga qarab "yashirinib qolmasin". Kelishilgan yondashuv: DM cheklangan
(REMINDER_MAX_PER_ORDER), asosiy vosita — operator qo'ng'irog'i.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from Data.unit_of_work import UnitOfWork
from Domain.constants import MAX_REORDER_SNOOZE_DAYS
from Domain.models.operator_call import CallOutcome, OperatorCall
from Service.exceptions import EntityNotFoundError, ValidationError
from Service.reminder_math import due_datetime

log = logging.getLogger(__name__)

# Segment nomlari — API'da string sifatida ishlatiladi (frontend filtri).
SEGMENT_ACTIVE = "active"
SEGMENT_DUE = "due"
SEGMENT_OVERDUE = "overdue"
SEGMENT_CHURNED = "churned"
# Operator uchun default ko'rinish — harakat talab qiladigan segmentlar.
ACTIONABLE_SEGMENTS = (SEGMENT_DUE, SEGMENT_OVERDUE, SEGMENT_CHURNED)


def _local_tz():
    try:
        from config import get_settings
        return ZoneInfo(get_settings().timezone)
    except Exception:
        return timezone(timedelta(hours=5))  # UTC+5 fallback (Toshkent)


@dataclass(slots=True)
class CustomerReorderStatus:
    """Bitta mijozning qayta-buyurtma holati (read-model, DB'da saqlanmaydi)."""
    customer_id: int
    telegram_id: int
    full_name: str
    phone_number: str
    segment: str
    orders_count: int              # DELIVERED buyurtmalar soni
    last_delivered_at: Optional[datetime]
    cycle_days: Optional[float]    # hisoblangan iste'mol sikli
    due_date: Optional[date]       # bazaviy (k=0) tugash sanasi (mahalliy)
    days_overdue: int              # bugun − due (manfiy = hali vaqt bor)
    reminders_sent: int            # oxirgi buyurtmadan keyingi DM'lar soni
    can_dm: bool                   # botga /start bosgan, DM mumkin
    has_open_order: bool
    snoozed_until: Optional[date]
    last_call_at: Optional[datetime]
    last_call_outcome: Optional[str]
    last_call_note: str = ""


@dataclass(slots=True)
class ReorderPage:
    items: List[CustomerReorderStatus]
    total: int
    counts: Dict[str, int]         # segment -> soni (filtrsiz, snooze'sizlar)


class CustomerLifecycleService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ---------------------- Hisoblash ----------------------

    async def compute_all(self) -> List[CustomerReorderStatus]:
        """Barcha aktiv mijozlarning qayta-buyurtma holati (segmentlangan).

        Bulk so'rovlar (N+1 yo'q): tarix/ochiq buyurtma/eslatma/qo'ng'iroqlar
        har biri bitta so'rov — reminder_service.run_once bilan bir xil naqsh.
        Hozirgi masshtabda (kichik biznes) live hisoblash yetarli tez; katta
        bazada `customer_reorder_status` projection jadvaliga ko'chiriladi.
        """
        tz = _local_tz()
        today = datetime.now(tz).date()

        async with UnitOfWork(self._sf) as uow:
            cfg = await uow.settings.get_or_create()
            lead_days = max(0, int(cfg.reminder_lead_days or 0))
            churn_after = max(1, int(getattr(cfg, "reorder_churn_after_days", 14) or 14))
            users = await uow.users.list_active()
            delivered = await uow.orders.all_delivered_for_cadence()
            open_set = await uow.orders.customers_with_open_order()
            sent_times = await uow.reminders.all_sent_times()
            snoozed = await uow.operator_calls.snoozed_until_map(today)
            last_calls = await uow.operator_calls.last_call_per_customer(
                [u.id for u in users]
            )

        history: dict[int, list[tuple[datetime, int]]] = {}
        for cid, _oid, dt, bottles in delivered:
            history.setdefault(cid, []).append((dt, bottles))
        rem_times: dict[int, list[datetime]] = {}
        for cid, t in sent_times:
            rem_times.setdefault(cid, []).append(t)

        out: List[CustomerReorderStatus] = []
        for u in users:
            hist = history.get(u.id)
            if not hist:
                continue  # buyurtmasiz mijozlar ro'yxatga kirmaydi

            last_delivered = hist[-1][0]
            k = sum(1 for t in rem_times.get(u.id, []) if t > last_delivered)

            # Bazaviy due (k=0) — operator haqiqiy kechikishni ko'radi.
            res = due_datetime(hist, reminders_since_order=0)
            has_open = u.id in open_set

            if res is None:
                # Oxirgi buyurtma idishsiz (pumpa/kuller) — sikl signal yo'q.
                cycle: Optional[float] = None
                due_local: Optional[date] = None
                diff = 0
                segment = SEGMENT_ACTIVE
            else:
                due_utc, cycle = res
                due_local = due_utc.astimezone(tz).date()
                diff = (today - due_local).days
                if has_open:
                    segment = SEGMENT_ACTIVE  # hozir buyurtma jarayonida
                elif diff < -lead_days:
                    segment = SEGMENT_ACTIVE
                elif diff <= 0:
                    segment = SEGMENT_DUE
                elif diff <= churn_after:
                    segment = SEGMENT_OVERDUE
                else:
                    segment = SEGMENT_CHURNED

            call = last_calls.get(u.id)
            out.append(CustomerReorderStatus(
                customer_id=u.id,
                telegram_id=int(u.telegram_id),
                full_name=u.full_name,
                phone_number=u.phone_number or "",
                segment=segment,
                orders_count=len(hist),
                last_delivered_at=last_delivered,
                cycle_days=round(float(cycle), 1) if cycle is not None else None,
                due_date=due_local,
                days_overdue=diff,
                reminders_sent=k,
                can_dm=bool(u.has_started_bot and int(u.telegram_id) > 0),
                has_open_order=has_open,
                snoozed_until=snoozed.get(u.id),
                last_call_at=call.called_at if call else None,
                last_call_outcome=call.outcome.value if call else None,
                last_call_note=(call.note if call else "") or "",
            ))
        return out

    async def reorder_list(
        self,
        *,
        segment: Optional[str] = None,
        include_snoozed: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> ReorderPage:
        """Aqlli eslatma sahifasi: filtrlangan + tartiblangan + paginatsiya.

        Default (`segment=None`) — harakat talab qiladigan uchala segment.
        Tartib: eng ko'p kechikkanlar birinchi (days_overdue desc).
        """
        all_items = await self.compute_all()

        # compute_all bilan BIR XIL "bugun" — mahalliy (Toshkent) sana.
        today = datetime.now(_local_tz()).date()
        counts: Dict[str, int] = {s: 0 for s in (
            SEGMENT_ACTIVE, SEGMENT_DUE, SEGMENT_OVERDUE, SEGMENT_CHURNED,
        )}
        for it in all_items:
            snoozed_now = it.snoozed_until is not None and it.snoozed_until >= today
            if not snoozed_now:
                counts[it.segment] = counts.get(it.segment, 0) + 1

        wanted = ACTIONABLE_SEGMENTS if not segment or segment == "all" else (segment,)
        filtered = [it for it in all_items if it.segment in wanted]
        if not include_snoozed:
            filtered = [
                it for it in filtered
                if not (it.snoozed_until is not None and it.snoozed_until >= today)
            ]
        filtered.sort(key=lambda it: (-it.days_overdue, it.due_date or today))

        total = len(filtered)
        return ReorderPage(
            items=filtered[offset:offset + limit],
            total=total,
            counts=counts,
        )

    # ---------------------- Operator qo'ng'irog'i ----------------------

    async def log_call(
        self,
        customer_id: int,
        *,
        operator_id: int,
        outcome: str,
        note: str = "",
        snooze_days: int = 0,
    ) -> OperatorCall:
        """Qo'ng'iroq natijasini qayd qiladi (append-only jurnal).

        `snooze_days > 0` — mijoz shuncha kun ro'yxatdan yashiriladi
        (istalgan outcome bilan birga ishlaydi; SNOOZED uchun majburiy).
        """
        try:
            oc = CallOutcome(outcome)
        except ValueError:
            raise ValidationError("call_outcome_invalid")
        snooze_days = max(0, int(snooze_days or 0))
        if snooze_days > MAX_REORDER_SNOOZE_DAYS:
            raise ValidationError(
                "snooze_too_long", context={"max": MAX_REORDER_SNOOZE_DAYS},
            )
        if oc == CallOutcome.SNOOZED and snooze_days == 0:
            snooze_days = 3  # oqilona default — "keyinroq" kamida 3 kun

        tz = _local_tz()
        today = datetime.now(tz).date()
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get(customer_id)
            if user is None:
                raise EntityNotFoundError("user_not_registered")
            call = OperatorCall(
                customer_id=customer_id,
                operator_id=int(operator_id),
                outcome=oc,
                snooze_until=(today + timedelta(days=snooze_days)) if snooze_days else None,
                note=(note or "").strip()[:255],
            )
            return await uow.operator_calls.add(call)

    async def call_history(self, customer_id: int, *, limit: int = 20):
        async with UnitOfWork(self._sf) as uow:
            return await uow.operator_calls.list_for_customer(customer_id, limit=limit)
