"""ReportService — Excel (.xlsx) hisobot: buyurtmalar, mijozlar, operatsiyalar.

Admin panelda sana oralig'i tanlanadi → bitta .xlsx fayl xotirada quriladi →
admin botga hujjat sifatida yuboriladi (Variant A: eng ishonchli yetkazish —
Telegram klient versiyasiga bog'liq emas, fayl chat tarixida arxiv bo'lib qoladi).

Arxitektura (functional core / imperative shell):
  * `_fetch_report_data` — async o'qish (SQLAlchemy), natija ODDIY dataclasslar
  * `_build_workbook`   — SOF sinxron funksiya: data → xlsx baytlar (XlsxWriter,
    in_memory). Event loop'ni bloklamaslik uchun `asyncio.to_thread` da yuritiladi.
  * `build_and_send`    — orkestr: fetch → build → botga yuborish.

Sana filtri: mahalliy (Toshkent) kun chegaralari [date_from 00:00, date_to 24:00)
UTC'ga o'girilib qo'llanadi. "Buyurtmalar" varag'i created_at bo'yicha, moliyaviy
xulosa esa delivered_at bo'yicha (pul haqiqatda qo'lga tekkan payt).
"""
from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional, Sequence

from aiogram import Bot
from aiogram.types import BufferedInputFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from Domain.enums import OrderStatus, PaymentMethod
from Domain.models.courier import Courier
from Domain.models.ledger import LedgerEntry, LedgerSubject
from Domain.models.order import Order, OrderItem
from Domain.models.user import User
from Domain.models.user_phone import UserPhone
from Service.exceptions import InvalidOperationError, ValidationError
from Service.order_display import order_display_number
from Service.timeutil import local_tz

log = logging.getLogger(__name__)

# Hisobot maksimal oralig'i — tasodifiy "10 yillik" so'rov DB'ni qiynamasin.
MAX_RANGE_DAYS = 400

# Ledger `kind` → o'zbekcha yorliq (yangi kind qo'shilsa xom nom ko'rinadi — buzilmaydi).
_KIND_UZ = {
    "opening_balance": "Boshlang'ich qoldiq",
    "cashback_earn": "Keshbek berildi",
    "cashback_spend": "Keshbek ishlatildi",
    "cashback_refund": "Keshbek qaytdi",
    "cashback_adjust": "Keshbek tuzatildi (admin)",
    "bottle_issue": "Idish berildi",
    "bottle_return": "Idish qaytdi",
    "bottle_adjust": "Idish tuzatildi (admin)",
    "cash_collect": "Naqd olindi (kuryer)",
    "cash_settle": "Naqd topshirildi",
    "deposit_topup": "Depozit to'ldirildi",
    "deposit_spend": "Depozitdan yechildi",
    "deposit_refund": "Depozitga qaytdi",
    "deposit_adjust": "Depozit tuzatildi (admin)",
}

_ACCOUNT_UZ = {
    "cashback": "Keshbek",
    "bottles": "Idish",
    "cash": "Naqd",
    "deposit": "Depozit",
}


# ---------------------------------------------------------------------------
# Data snapshot (fetch natijasi — build uchun ODDIY qiymatlar, ORM emas)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class OrderRow:
    display_number: str
    created_local: str
    status_label: str
    customer_name: str
    contact_phone: str
    courier_name: str
    items_text: str
    items_total: Decimal
    cashback_used: Decimal
    cashback_earned: Decimal
    total_amount: Decimal
    payment_label: str
    delivered_local: str


@dataclass(slots=True)
class CustomerRow:
    full_name: str
    phones: str
    cashback_balance: Decimal
    bottles_balance: int
    deposit_balance: Decimal
    period_orders: int
    period_spent: Decimal
    registered_local: str


@dataclass(slots=True)
class LedgerRow:
    created_local: str
    subject_label: str
    subject_name: str
    account_label: str
    kind_label: str
    delta: Decimal
    balance_after: Decimal
    order_no: str
    reason: str


@dataclass(slots=True)
class ExpenseRow:
    spent_on: str          # dd.mm.yyyy
    category: str
    note: str
    source_label: str      # "Doimiy" (shablondan) | "Bir martalik"
    amount: Decimal


@dataclass(slots=True)
class ReportData:
    period_label: str
    orders: list[OrderRow] = field(default_factory=list)
    customers: list[CustomerRow] = field(default_factory=list)
    entries: list[LedgerRow] = field(default_factory=list)
    expenses: list[ExpenseRow] = field(default_factory=list)
    # Xulosa ko'rsatkichlari
    orders_created: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    delivered_count: int = 0
    delivered_items_total: Decimal = Decimal("0")
    delivered_total: Decimal = Decimal("0")
    cashback_used_sum: Decimal = Decimal("0")
    cashback_earned_sum: Decimal = Decimal("0")
    payment_breakdown: dict[str, tuple[int, Decimal]] = field(default_factory=dict)
    bottles_issued_sum: int = 0
    bottles_returned_sum: int = 0
    new_customers: int = 0
    # P&L bloki — Moliya dashboard formulasi bilan AYNAN bir xil:
    # sof foyda = tushum (total_amount) − tannarx (COGS) − rasxodlar.
    cogs: Decimal = Decimal("0")
    expenses_total: Decimal = Decimal("0")
    expenses_by_cat: list[tuple[str, Decimal]] = field(default_factory=list)
    net_profit: Decimal = Decimal("0")


@dataclass(slots=True)
class ReportResult:
    filename: str
    size_bytes: int
    orders: int
    customers: int
    entries: int
    sent: bool
    send_error: str = ""


# ---------------------------------------------------------------------------
# Yordamchilar
# ---------------------------------------------------------------------------

def _utc_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    """Mahalliy kun chegaralari [from 00:00, to+1 00:00) → UTC."""
    tz = local_tz()
    start = datetime.combine(date_from, time.min, tzinfo=tz)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _fmt_local(dt: Optional[datetime]) -> str:
    """DB datetime (UTC; SQLite'da naive) → mahalliy 'dd.mm.yyyy HH:MM'."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(local_tz()).strftime("%d.%m.%Y %H:%M")


def _payment_label(raw: Optional[str]) -> str:
    try:
        return PaymentMethod(raw).label_uz if raw else ""
    except ValueError:
        return raw or ""


def _money(v) -> Decimal:
    return Decimal(str(v or 0))


class ReportService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        admin_bot: Bot,
        expense_service,
    ) -> None:
        self._sf = session_factory
        self._bot = admin_bot
        # ExpenseService — rasmiy yo'l: summary() doimiy shablonlarni avval
        # materializatsiya qiladi (aks holda davr rasxodlari chala chiqardi).
        self._expenses = expense_service

    # ------------------------------------------------------------------
    # Jamoat API
    # ------------------------------------------------------------------

    async def build_and_send(
        self, *, date_from: date, date_to: date, admin_telegram_id: int,
    ) -> ReportResult:
        """Hisobotni quradi va so'ragan adminning o'ziga DM qiladi."""
        xlsx, data = await self.build_excel(date_from=date_from, date_to=date_to)
        filename = f"hisobot_{date_from.isoformat()}_{date_to.isoformat()}.xlsx"
        caption = (
            f"📊 <b>Hisobot</b> {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}\n"
            f"Buyurtmalar: {len(data.orders)} | Mijozlar: {len(data.customers)} "
            f"| Operatsiyalar: {len(data.entries)} | Rasxodlar: {len(data.expenses)}"
        )
        sent, err = True, ""
        try:
            await self._bot.send_document(
                chat_id=admin_telegram_id,
                document=BufferedInputFile(xlsx, filename=filename),
                caption=caption,
            )
        except Exception as e:  # DM yopiq / tarmoq — aniq xabar bilan qaytamiz
            sent, err = False, str(e)
            log.warning("Hisobot adminga (tg=%s) yuborilmadi: %s", admin_telegram_id, e)
        return ReportResult(
            filename=filename, size_bytes=len(xlsx),
            orders=len(data.orders), customers=len(data.customers),
            entries=len(data.entries), sent=sent, send_error=err,
        )

    async def build_excel(
        self, *, date_from: date, date_to: date,
    ) -> tuple[bytes, ReportData]:
        """Hisobot faylini quradi (yubormasdan) — test va kelajakdagi
        downloadFile varianti ham shu yadrodan foydalanadi."""
        if date_from > date_to:
            raise ValidationError(
                "date_range_invalid",
                message="Boshlanish sanasi tugash sanasidan keyin bo'lishi mumkin emas.",
            )
        if (date_to - date_from).days > MAX_RANGE_DAYS:
            raise ValidationError(
                "date_range_too_long",
                message=f"Hisobot oralig'i {MAX_RANGE_DAYS} kundan oshmasin.",
            )
        # XlsxWriter LAZY tekshiriladi — kutubxona o'rnatilmagan deploy'da
        # BUTUN tizim (3 bot + API) o'lib qolmasin (modul-darajali import
        # aynan shunday qilardi); faqat shu endpoint aniq xato qaytaradi.
        import importlib.util
        if importlib.util.find_spec("xlsxwriter") is None:
            raise InvalidOperationError(
                "xlsx_lib_missing",
                message=(
                    "Serverda XlsxWriter o'rnatilmagan — "
                    "`pip install -r requirements.txt` bajarib restart qiling."
                ),
            )
        data = await self._fetch_report_data(date_from, date_to)
        xlsx = await asyncio.to_thread(_build_workbook, data)
        return xlsx, data

    # ------------------------------------------------------------------
    # O'qish (async) — natija oddiy dataclasslar
    # ------------------------------------------------------------------

    async def _fetch_report_data(self, date_from: date, date_to: date) -> ReportData:
        start_utc, end_utc = _utc_bounds(date_from, date_to)
        data = ReportData(
            period_label=f"{date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}",
        )
        # Rasxod xulosasi ALDIN — summary() doimiy shablonlarni materializatsiya
        # qiladi (o'z tranzaksiyasida), keyin biz qatorlarni o'qiymiz.
        exp_summary = await self._expenses.summary(date_from, date_to)
        data.expenses_total = _money(exp_summary.total)
        data.expenses_by_cat = [
            (name, _money(total)) for _, name, total in exp_summary.by_category
        ]
        async with self._sf() as s:
            await self._fetch_orders(s, data, start_utc, end_utc)
            await self._fetch_customers(s, data, start_utc, end_utc)
            await self._fetch_ledger(s, data, start_utc, end_utc)
            await self._fetch_expenses(s, data, date_from, date_to)
        # Sof foyda — Moliya dashboard bilan bir xil formula.
        data.net_profit = (
            data.delivered_total - data.cogs - data.expenses_total
        ).quantize(Decimal("0.01"))
        return data

    async def _fetch_orders(
        self, s: AsyncSession, data: ReportData, start_utc, end_utc,
    ) -> None:
        # deleted_at filtri — arxivlangan (test/spam) buyurtmalar hisobotga
        # KIRMAYDI: Moliya dashboard (`finance_in_window`) bilan raqamlar
        # aynan mos bo'lishi shart. items.food noload — faqat food_name
        # snapshot kerak, foods jadvalini tortish shart emas.
        orders = (await s.execute(
            select(Order)
            .options(
                selectinload(Order.items).noload(OrderItem.food),
                selectinload(Order.customer),
                selectinload(Order.courier),
            )
            .where(
                Order.deleted_at.is_(None),
                Order.created_at >= start_utc,
                Order.created_at < end_utc,
            )
            .order_by(Order.created_at.asc(), Order.id.asc())
        )).scalars().all()

        data.orders_created = len(orders)
        for o in orders:
            data.status_counts[o.status.label_uz] = (
                data.status_counts.get(o.status.label_uz, 0) + 1
            )
            items_text = "; ".join(
                f"{it.food_name} ×{int(it.effective_quantity)}" for it in o.items
            )
            data.orders.append(OrderRow(
                display_number=order_display_number(o),
                created_local=_fmt_local(o.created_at),
                status_label=o.status.label_uz,
                customer_name=(o.customer.full_name if o.customer else ""),
                contact_phone=o.contact_phone or "",
                courier_name=(o.courier.full_name if o.courier else ""),
                items_text=items_text,
                items_total=_money(o.items_total),
                cashback_used=_money(o.cashback_used),
                cashback_earned=_money(o.cashback_earned),
                total_amount=_money(o.total_amount),
                payment_label=_payment_label(o.payment_method),
                delivered_local=_fmt_local(o.delivered_at),
            ))

        # Moliyaviy xulosa — delivered_at oynasi bo'yicha (pul qo'lga tekkan
        # payt). AGGREGATE so'rovlar: ORM obyektlar (va ularning selectin
        # kaskadi) yuklanmaydi — 10k buyurtmali oyda ham yengil.
        delivered_where = (
            Order.deleted_at.is_(None),
            Order.status == OrderStatus.DELIVERED,
            Order.delivered_at >= start_utc,
            Order.delivered_at < end_utc,
        )
        totals = (await s.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(Order.items_total), 0),
                func.coalesce(func.sum(Order.total_amount), 0),
                func.coalesce(func.sum(Order.cashback_used), 0),
                func.coalesce(func.sum(Order.cashback_earned), 0),
                func.coalesce(func.sum(Order.bottles_issued), 0),
                func.coalesce(func.sum(Order.bottles_returned), 0),
            ).where(*delivered_where)
        )).one()
        data.delivered_count = int(totals[0] or 0)
        data.delivered_items_total = _money(totals[1])
        data.delivered_total = _money(totals[2])
        data.cashback_used_sum = _money(totals[3])
        data.cashback_earned_sum = _money(totals[4])
        data.bottles_issued_sum = int(totals[5] or 0)
        data.bottles_returned_sum = int(totals[6] or 0)

        for method, cnt, total in (await s.execute(
            select(
                Order.payment_method,
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_amount), 0),
            ).where(*delivered_where).group_by(Order.payment_method)
        )).all():
            label = _payment_label(method) or "Noma'lum"
            data.payment_breakdown[label] = (int(cnt), _money(total))

        # Tannarx (COGS) — cogs_in_window bilan bir xil formula: Σ unit_cost ×
        # effective dona, FAQAT delivered oynasi (dashboard bilan mos).
        eff_qty = func.coalesce(OrderItem.delivered_quantity, OrderItem.quantity)
        cogs = (await s.execute(
            select(func.coalesce(func.sum(OrderItem.unit_cost * eff_qty), 0))
            .join(Order, OrderItem.order_id == Order.id)
            .where(*delivered_where)
        )).scalar_one()
        data.cogs = _money(cogs)

    async def _fetch_customers(
        self, s: AsyncSession, data: ReportData, start_utc, end_utc,
    ) -> None:
        users = (await s.execute(
            select(User)
            .where(User.deleted_at.is_(None))
            .order_by(User.full_name.asc())
        )).scalars().all()

        # Telefonlar — bitta so'rov, user_id bo'yicha guruhlab olamiz.
        phone_rows = (await s.execute(
            select(UserPhone.user_id, UserPhone.phone, UserPhone.is_primary)
            .order_by(UserPhone.is_primary.desc(), UserPhone.id.asc())
        )).all()
        phones_by_user: dict[int, list[str]] = {}
        for user_id, phone, _ in phone_rows:
            phones_by_user.setdefault(user_id, []).append(phone)

        # Davr statistikasi — bitta GROUP BY (buyurtmalar soni created bo'yicha,
        # xarid summasi delivered bo'yicha).
        created_stats = dict((await s.execute(
            select(Order.customer_id, func.count(Order.id))
            .where(
                Order.deleted_at.is_(None),
                Order.created_at >= start_utc,
                Order.created_at < end_utc,
            )
            .group_by(Order.customer_id)
        )).all())
        spent_stats = dict((await s.execute(
            select(Order.customer_id, func.coalesce(func.sum(Order.total_amount), 0))
            .where(
                Order.deleted_at.is_(None),
                Order.status == OrderStatus.DELIVERED,
                Order.delivered_at >= start_utc,
                Order.delivered_at < end_utc,
            )
            .group_by(Order.customer_id)
        )).all())

        for u in users:
            phones = phones_by_user.get(u.id) or ([u.phone_number] if u.phone_number else [])
            data.customers.append(CustomerRow(
                full_name=u.full_name or "",
                phones=", ".join(p for p in phones if p),
                cashback_balance=_money(u.cashback_balance),
                bottles_balance=int(u.bottles_balance or 0),
                deposit_balance=_money(getattr(u, "deposit_balance", 0)),
                period_orders=int(created_stats.get(u.id, 0)),
                period_spent=_money(spent_stats.get(u.id, 0)),
                registered_local=_fmt_local(u.created_at),
            ))
            created = u.created_at
            if created is not None:
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if start_utc <= created < end_utc:
                    data.new_customers += 1

    async def _fetch_ledger(
        self, s: AsyncSession, data: ReportData, start_utc, end_utc,
    ) -> None:
        entries = (await s.execute(
            select(LedgerEntry)
            .where(LedgerEntry.created_at >= start_utc, LedgerEntry.created_at < end_utc)
            .order_by(LedgerEntry.id.asc())
        )).scalars().all()
        if not entries:
            return

        user_ids = {e.subject_id for e in entries if e.subject_type == LedgerSubject.USER.value}
        courier_ids = {e.subject_id for e in entries if e.subject_type == LedgerSubject.COURIER.value}
        user_names: dict[int, str] = {}
        courier_names: dict[int, str] = {}
        if user_ids:
            user_names = dict((await s.execute(
                select(User.id, User.full_name).where(User.id.in_(user_ids))
            )).all())
        if courier_ids:
            courier_names = dict((await s.execute(
                select(Courier.id, Courier.full_name).where(Courier.id.in_(courier_ids))
            )).all())

        # Buyurtma raqamlari (display) — ledger qatoriga odam o'qiy oladigan №.
        # Faqat 3 skalyar ustun — to'liq ORM Order (selectin kaskadi bilan)
        # yuklanmaydi. Arxivlangan buyurtma raqami ham ko'rsatiladi (ledger
        # yozuvi tarixiy fakt, raqami o'qilishi kerak).
        order_ids = {e.order_id for e in entries if e.order_id}
        order_numbers: dict[int, str] = {}
        if order_ids:
            for oid, daily, created in (await s.execute(
                select(Order.id, Order.daily_number, Order.created_at)
                .where(Order.id.in_(order_ids))
            )).all():
                order_numbers[oid] = order_display_number(SimpleNamespace(
                    id=oid, daily_number=daily, created_at=created,
                ))

        for e in entries:
            if e.subject_type == LedgerSubject.USER.value:
                subject_label, name = "Mijoz", user_names.get(e.subject_id, f"#{e.subject_id}")
            else:
                subject_label, name = "Kuryer", courier_names.get(e.subject_id, f"#{e.subject_id}")
            data.entries.append(LedgerRow(
                created_local=_fmt_local(e.created_at),
                subject_label=subject_label,
                subject_name=name or "",
                account_label=_ACCOUNT_UZ.get(e.account, e.account),
                kind_label=_KIND_UZ.get(e.kind, e.kind),
                delta=_money(e.delta),
                balance_after=_money(e.balance_after),
                order_no=order_numbers.get(e.order_id, "") if e.order_id else "",
                reason=e.reason or "",
            ))


    async def _fetch_expenses(
        self, s: AsyncSession, data: ReportData, date_from: date, date_to: date,
    ) -> None:
        """Rasxod qatorlari — admin panel "Ro'yxat" bilan bir xil oyna semantikasi
        (qamrovli/oldindan to'langan yozuvlar davr bilan kesishsa ham chiqadi;
        Xulosadagi jami esa rasmiy proportsional summary'dan)."""
        from Data.repositories.expense_repository import ExpenseRepository

        rows = await ExpenseRepository(s).list_in_window(
            date_from, date_to, limit=100_000,
        )
        for e in rows:
            data.expenses.append(ExpenseRow(
                spent_on=e.spent_on.strftime("%d.%m.%Y") if e.spent_on else "",
                category=(e.category.name if e.category else ""),
                note=e.note or "",
                source_label="Doimiy" if e.recurring_id else "Bir martalik",
                amount=_money(e.amount),
            ))


# ---------------------------------------------------------------------------
# SOF workbook quruvchi (sinxron — to_thread ichida yuritiladi)
# ---------------------------------------------------------------------------

def _build_workbook(data: ReportData) -> bytes:
    import xlsxwriter  # lazy — modul yuklanishi tizim boot'iga bog'lanmasin

    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})

    # Dizayn tokenlari — admin panel palitrasi bilan mos (#0088CC primary).
    f_title = wb.add_format({"bold": True, "font_size": 14, "font_color": "#003F7F"})
    f_header = wb.add_format({
        "bold": True, "font_color": "#FFFFFF", "bg_color": "#0088CC",
        "border": 1, "border_color": "#006DA3", "valign": "vcenter",
    })
    f_money = wb.add_format({"num_format": "#,##0"})
    f_money_bold = wb.add_format({"num_format": "#,##0", "bold": True})
    f_int = wb.add_format({"num_format": "0"})
    f_label = wb.add_format({"bold": True})

    def _sheet(name: str, headers: Sequence[str], widths: Sequence[int]):
        ws = wb.add_worksheet(name)
        for col, (h, w) in enumerate(zip(headers, widths)):
            ws.set_column(col, col, w)
            ws.write_string(0, col, h, f_header)
        ws.freeze_panes(1, 0)
        if headers:
            ws.autofilter(0, 0, 0, len(headers) - 1)
        return ws

    # ---- 1. Xulosa ----
    ws = wb.add_worksheet("Xulosa")
    ws.set_column(0, 0, 38)
    ws.set_column(1, 1, 20)
    ws.write_string(0, 0, f"Hisobot davri: {data.period_label}", f_title)

    r = 2
    ws.write_string(r, 0, "Yaratilgan buyurtmalar", f_label)
    ws.write_number(r, 1, data.orders_created, f_int)
    r += 1
    for label, cnt in sorted(data.status_counts.items()):
        ws.write_string(r, 0, f"    {label}")
        ws.write_number(r, 1, cnt, f_int)
        r += 1
    r += 1
    ws.write_string(r, 0, "Yetkazib berilgan buyurtmalar", f_label)
    ws.write_number(r, 1, data.delivered_count, f_int); r += 1
    ws.write_string(r, 0, "Savdo (mahsulotlar summasi, so'm)", f_label)
    ws.write_number(r, 1, float(data.delivered_items_total), f_money_bold); r += 1
    ws.write_string(r, 0, "Tushum (keshbekdan keyin, so'm)", f_label)
    ws.write_number(r, 1, float(data.delivered_total), f_money_bold); r += 1
    ws.write_string(r, 0, "Keshbek ishlatildi (so'm)")
    ws.write_number(r, 1, float(data.cashback_used_sum), f_money); r += 1
    ws.write_string(r, 0, "Keshbek berildi (so'm)")
    ws.write_number(r, 1, float(data.cashback_earned_sum), f_money); r += 2
    for label, (cnt, total) in sorted(data.payment_breakdown.items()):
        ws.write_string(r, 0, f"To'lov: {label} ({cnt} ta, so'm)")
        ws.write_number(r, 1, float(total), f_money)
        r += 1
    r += 1
    # P&L bloki — Moliya dashboard formulasi: tushum − tannarx − rasxodlar.
    ws.write_string(r, 0, "Tannarx (COGS, so'm)")
    ws.write_number(r, 1, float(data.cogs), f_money); r += 1
    ws.write_string(r, 0, "Rasxodlar jami (so'm)", f_label)
    ws.write_number(r, 1, float(data.expenses_total), f_money_bold); r += 1
    for cat_name, cat_total in data.expenses_by_cat:
        ws.write_string(r, 0, f"    {cat_name} (so'm)")
        ws.write_number(r, 1, float(cat_total), f_money)
        r += 1
    net_fmt = wb.add_format({
        "num_format": "#,##0", "bold": True,
        "font_color": "#27AE60" if data.net_profit >= 0 else "#E74C3C",
    })
    ws.write_string(r, 0, "SOF FOYDA (tushum − tannarx − rasxodlar, so'm)", f_label)
    ws.write_number(r, 1, float(data.net_profit), net_fmt); r += 2
    ws.write_string(r, 0, "Idish berildi (dona)")
    ws.write_number(r, 1, data.bottles_issued_sum, f_int); r += 1
    ws.write_string(r, 0, "Idish qaytdi (dona)")
    ws.write_number(r, 1, data.bottles_returned_sum, f_int); r += 1
    ws.write_string(r, 0, "Yangi mijozlar (davrda)")
    ws.write_number(r, 1, data.new_customers, f_int)

    # ---- 2. Buyurtmalar ----
    ws = _sheet(
        "Buyurtmalar",
        ["№", "Yaratildi", "Holat", "Mijoz", "Telefon", "Kuryer", "Mahsulotlar",
         "Mahsulot summasi", "Keshbek ishlatildi", "Keshbek berildi",
         "Jami (so'm)", "To'lov", "Yetkazildi"],
        [14, 17, 15, 22, 15, 18, 34, 15, 15, 14, 13, 11, 17],
    )
    for r, o in enumerate(data.orders, start=1):
        ws.write_string(r, 0, o.display_number)
        ws.write_string(r, 1, o.created_local)
        ws.write_string(r, 2, o.status_label)
        ws.write_string(r, 3, o.customer_name)
        ws.write_string(r, 4, o.contact_phone)
        ws.write_string(r, 5, o.courier_name)
        ws.write_string(r, 6, o.items_text)
        ws.write_number(r, 7, float(o.items_total), f_money)
        ws.write_number(r, 8, float(o.cashback_used), f_money)
        ws.write_number(r, 9, float(o.cashback_earned), f_money)
        ws.write_number(r, 10, float(o.total_amount), f_money_bold)
        ws.write_string(r, 11, o.payment_label)
        ws.write_string(r, 12, o.delivered_local)

    # ---- 3. Mijozlar ----
    ws = _sheet(
        "Mijozlar",
        ["Ism", "Telefonlar", "Keshbek balans", "Idish balans", "Depozit balans",
         "Davrda buyurtma", "Davrda xarid (so'm)", "Ro'yxatdan o'tdi"],
        [26, 30, 14, 12, 14, 14, 16, 17],
    )
    for r, c in enumerate(data.customers, start=1):
        ws.write_string(r, 0, c.full_name)
        ws.write_string(r, 1, c.phones)
        ws.write_number(r, 2, float(c.cashback_balance), f_money)
        ws.write_number(r, 3, c.bottles_balance, f_int)
        ws.write_number(r, 4, float(c.deposit_balance), f_money)
        ws.write_number(r, 5, c.period_orders, f_int)
        ws.write_number(r, 6, float(c.period_spent), f_money)
        ws.write_string(r, 7, c.registered_local)

    # ---- 4. Operatsiyalar (ledger) ----
    ws = _sheet(
        "Operatsiyalar",
        ["Sana", "Kim", "Ism", "Hisob", "Operatsiya", "O'zgarish", "Qoldiq",
         "Buyurtma №", "Izoh"],
        [17, 8, 22, 10, 24, 13, 13, 14, 40],
    )
    for r, e in enumerate(data.entries, start=1):
        ws.write_string(r, 0, e.created_local)
        ws.write_string(r, 1, e.subject_label)
        ws.write_string(r, 2, e.subject_name)
        ws.write_string(r, 3, e.account_label)
        ws.write_string(r, 4, e.kind_label)
        ws.write_number(r, 5, float(e.delta), f_money)
        ws.write_number(r, 6, float(e.balance_after), f_money)
        ws.write_string(r, 7, e.order_no)
        ws.write_string(r, 8, e.reason)

    # ---- 5. Rasxodlar ----
    ws = _sheet(
        "Rasxodlar",
        ["Sana", "Kategoriya", "Izoh", "Turi", "Summa (so'm)"],
        [12, 22, 36, 13, 14],
    )
    for r, e in enumerate(data.expenses, start=1):
        ws.write_string(r, 0, e.spent_on)
        ws.write_string(r, 1, e.category)
        ws.write_string(r, 2, e.note)
        ws.write_string(r, 3, e.source_label)
        ws.write_number(r, 4, float(e.amount), f_money)

    wb.close()
    return buf.getvalue()
