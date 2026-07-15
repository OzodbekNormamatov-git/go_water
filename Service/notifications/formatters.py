"""Notification matn quruvchilari — sof funksiyalar, Telegram ga bog'liq emas.

Test'lash oson: input → output. Hech qanday I/O yo'q.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as _tz
from typing import Optional

from Domain.enums import OrderStatus, PaymentMethod
from Domain.models.order import Order
from Service.order_display import order_daily_label, order_display_number


def _payment_of(order: Order) -> PaymentMethod:
    """Order'ning to'lov usuli (eski qatorlarda ustun bo'lmasa — naqd)."""
    raw = str(getattr(order, "payment_method", "cash") or "cash")
    try:
        return PaymentMethod(raw)
    except ValueError:
        return PaymentMethod.CASH


def _payment_note_courier(pm: PaymentMethod, amount) -> str:
    """Kuryer/guruh xabari uchun to'lov qatori — kuryer pul olish-olmasligini
    bir qarashda bilsin."""
    if pm == PaymentMethod.CASH:
        return f"💰 <b>{amount} so'm</b> (💵 naqd — kuryer oladi)"
    if pm == PaymentMethod.CARD:
        return f"💰 <b>{amount} so'm</b> (💳 karta — <u>naqd olinmaydi</u>)"
    return f"💰 <b>{amount} so'm</b> (💰 balansdan to'langan — <u>naqd olinmaydi</u>)"


def _payment_note_customer(pm: PaymentMethod, amount) -> str:
    if pm == PaymentMethod.CASH:
        return f"💵 Jami: <b>{amount} so'm</b> (naqd kuryerga)"
    if pm == PaymentMethod.CARD:
        return f"💳 Jami: <b>{amount} so'm</b> (karta orqali)"
    return f"💰 Jami: <b>{amount} so'm</b> (balansingizdan to'landi)"


def _courier_head(order: Order) -> str:
    """Kuryer xabarlari uchun ENG TEPADAGI kunlik tartib raqami qatori.

    Kuryerlar kun davomida qisqa "№ 02" raqami bilan ishlaydi — to'liq
    "20260611-02" id pastda qoladi. Eski orderlarda (daily_number NULL) bo'sh.
    """
    label = order_daily_label(order)
    return f"<b>№ {label}</b>\n" if label else ""


# Toshkent vaqti — config'dan o'qish kerak edi, lekin formatter sof funksiya bo'lib
# qolishi uchun lazy importga aylantiramiz.
def _tz_local():
    try:
        from config import get_settings
        from zoneinfo import ZoneInfo
        return ZoneInfo(get_settings().timezone)
    except Exception:
        # Fallback: UTC+5 (Toshkent)
        return _tz(timedelta(hours=5))


def fmt_time(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    try:
        local = dt.astimezone(_tz_local())
    except Exception:
        local = dt
    return local.strftime("%H:%M")


def maps_link(lat: float, lon: float) -> str:
    return f"https://maps.google.com/?q={lat},{lon}"


def _items_short(order: Order) -> str:
    lines = []
    for it in (order.items or []):
        eff = int(getattr(it, "effective_quantity", it.quantity))
        # Kuryer yetkazishda miqdorni o'zgartirgan bo'lsa — ikkalasini ko'rsatamiz
        # ("× 6 (buyurtma: 4)"), aks holda oddiy "× 4".
        if getattr(it, "is_quantity_adjusted", False):
            lines.append(f"  • {it.food_name} × {eff} <i>(buyurtma: {int(it.quantity)})</i>")
        else:
            lines.append(f"  • {it.food_name} × {eff}")
    return "\n".join(lines)


# ---------------------- Couriers group ----------------------

def format_group_log(order: Order) -> str:
    """Admin LOG — kuryerlar guruhi endi faqat kuzatish uchun (tugmasiz).

    Bitta xabar buyurtma hayot tsikli davomida tahrirlanib boradi: yangi →
    olindi (kim) → yo'lda → yetib bordi → yetkazildi. Admin nima bo'layotganini
    real vaqt rejimida ko'rib turadi. Claim/ish kuryerning web ilovasida."""
    operator_badge = "  <i>(📞 operator)</i>" if getattr(order, "created_by_operator_id", None) else ""
    lines: list[str] = []
    head = _courier_head(order).rstrip("\n")
    if head:
        lines.append(head)
    lines.append(
        f"<b>{order.status.emoji} {order_display_number(order)} — {order.status.label_uz}</b>{operator_badge}"
    )
    lines.append(f"👤 {order.customer.full_name} · 📞 <code>{order.contact_phone}</code>")
    addr = (order.address_details or "").strip()
    lines.append(
        f"📍 <a href='{maps_link(order.delivery_latitude, order.delivery_longitude)}'>xarita</a>"
        + (f" · {addr}" if addr else "")
    )
    lines.append(f"🧺 {_items_short(order)}")
    lines.append(_payment_note_courier(_payment_of(order), order.total_amount))
    if order.courier is not None:
        ph = f" · 📞 {order.courier.phone_number}" if order.courier.phone_number else ""
        lines.append(f"🚚 Kuryer: <b>{order.courier.full_name}</b>{ph}")
    if order.delivered_at and (int(order.bottles_issued or 0) or int(order.bottles_returned or 0)):
        lines.append(
            f"♻️ Idish: berildi {int(order.bottles_issued or 0)}, "
            f"qaytdi {int(order.bottles_returned or 0)}"
        )
    if order.note:
        lines.append(f"📝 {order.note}")
    return "\n".join(lines)


# ---------------------- Customer DM (yagona timeline) ----------------------

def format_customer_timeline(order: Order, brand_name: str) -> str:
    """Mijoz DM da yagona xabar — har transitsiyada o'sib boruvchi timeline."""
    head = f"<b>📦 Buyurtma {order_display_number(order)}</b>"
    status_line = f"Holat: <b>{order.status.label_uz}</b>"

    timeline: list[str] = []

    if order.created_at:
        timeline.append(f"{OrderStatus.NEW.emoji} <b>{fmt_time(order.created_at)}</b> — Buyurtma qabul qilindi")

    if order.accepted_at and order.courier is not None:
        courier_name = order.courier.full_name
        username = f" (@{order.courier.username})" if order.courier.username else ""
        # Telefon — alohida satr, `tel:` link Telegram'da bosiladi (mobile'da
        # darhol qo'ng'iroq dialogini ochadi). Telefon yo'q bo'lsa, qator ham yo'q.
        phone_line = ""
        if order.courier.phone_number:
            phone_line = (
                f'\n    📞 <a href="tel:{order.courier.phone_number}">'
                f'{order.courier.phone_number}</a>'
            )
        timeline.append(
            f"{OrderStatus.ACCEPTED.emoji} <b>{fmt_time(order.accepted_at)}</b> — "
            f"Kuryer biriktirildi: <b>{courier_name}</b>{username}{phone_line}"
        )

    if getattr(order, "delivering_at", None):
        timeline.append(
            f"{OrderStatus.DELIVERING.emoji} <b>{fmt_time(order.delivering_at)}</b> — Kuryer yo'lga chiqdi"
        )

    if getattr(order, "arrived_at", None):
        timeline.append(
            f"{OrderStatus.ARRIVED.emoji} <b>{fmt_time(order.arrived_at)}</b> — Kuryer yetib keldi"
        )

    if order.delivered_at:
        # Yetkazib berildi qatoriga — kuryer olib ketgan bo'sh idishlar haqida ma'lumot
        # (mijoz checkout'da kiritmaydi — kuryer yetkazganda hisoblaydi va saqlaydi)
        bottles_taken = int(order.bottles_returned or 0)
        bottles_info = (
            f"\n    ♻️ Bo'sh idishlar olindi: <b>{bottles_taken}</b> ta"
            if bottles_taken > 0
            else "\n    ♻️ Bo'sh idish olinmadi"
        )
        timeline.append(
            f"{OrderStatus.DELIVERED.emoji} <b>{fmt_time(order.delivered_at)}</b> — "
            f"Yetkazib berildi{bottles_info}"
        )

    if order.cancelled_at:
        timeline.append(
            f"{OrderStatus.CANCELLED.emoji} <b>{fmt_time(order.cancelled_at)}</b> — Bekor qilindi"
        )

    items = _items_short(order)
    total = _payment_note_customer(_payment_of(order), order.total_amount)

    parts = [head, status_line, ""]
    if timeline:
        parts.extend(timeline)
        parts.append("")
    parts.append("<b>Tarkibi:</b>")
    if items:
        parts.append(items)
    parts.append("")
    parts.append(total)

    if order.status == OrderStatus.DELIVERED:
        parts.append("")
        parts.append(f"<b>{brand_name}</b> ni tanlaganingiz uchun minnatdormiz! 💧")

    return "\n".join(parts)


# ---------------------- Customer ARRIVED notification ----------------------

def format_customer_arrived(order: Order) -> str:
    """Mijozga qisqa, e'tibor jalb qiluvchi "yetib keldi!" xabar.

    Asosiy timeline xabariga TEGMAYDI — bu alohida push-notification kabi
    yangi xabar. DELIVERED bo'lganda o'chiriladi (chiqindi qoldirmaymiz).
    """
    courier = order.courier
    courier_part = ""
    if courier:
        courier_part = f"\nKuryer: <b>{courier.full_name}</b>"
        if courier.username:
            courier_part += f" (@{courier.username})"
        if courier.phone_number:
            courier_part += (
                f'\n📞 <a href="tel:{courier.phone_number}">{courier.phone_number}</a>'
            )
    return (
        f"🔔 <b>Buyurtmangiz {order_display_number(order)} yetib keldi!</b>\n"
        f"Iltimos, kuryerni qarshi oling."
        f"{courier_part}"
    )


