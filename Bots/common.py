from __future__ import annotations

import logging
import os
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent, FSInputFile, Message

log = logging.getLogger(__name__)


def register_error_handler(dp: Dispatcher, bot_name: str) -> None:
    """Dispatcher'ga yakuniy xato-to'ri: kutilmagan exception handler'dan
    chiqib ketsa foydalanuvchi javobsiz qolmasin (FSM osilib turmasin).

    DomainError'lar handler'larda tutiladi (i18n matn bilan) — bu to'r faqat
    haqiqatan kutilmagan xatolar (DB uzilishi, dasturchi bug'i) uchun.
    Foydalanuvchiga UMUMIY xabar boradi — ichki tafsilot chatga oqmaydi.
    """

    @dp.errors()
    async def _on_error(event: ErrorEvent) -> bool:
        log.exception(
            "[%s] Kutilmagan xato update ishlashda: %s",
            bot_name, event.exception,
        )
        # Best-effort — foydalanuvchiga bildiramiz (message yoki callback).
        try:
            upd = event.update
            msg = getattr(upd, "message", None)
            cb = getattr(upd, "callback_query", None)
            text = "❗️ Kutilmagan xatolik yuz berdi. Birozdan so'ng qayta urinib ko'ring."
            if msg is not None:
                await msg.answer(text)
            elif cb is not None:
                await cb.answer(text, show_alert=True)
        except TelegramAPIError:
            pass
        return True  # xato qayta ishlandi — aiogram default log'ini takrorlamaydi

# Loyiha ildizidagi media katalogi. Telegram file_id har bot uchun alohida
# bo'lgani uchun (admin bot olgan file_id'ni customer bot ishlatolmaydi),
# rasmlarni diskda saqlaymiz va har bir bot o'zi yuboradi.
MEDIA_ROOT = Path(__file__).resolve().parent.parent / "media"
FOODS_DIR = MEDIA_ROOT / "foods"


def fmt_money(amount: Decimal | float | int, currency: str | None = None) -> str:
    """Tiyinlarsiz, 1000 likni probel bilan ajratamiz: 22000 → "22 000 so'm".

    `currency` berilmasa, config'dagi `currency_symbol` ishlatiladi.
    """
    if currency is None:
        # Lazy import — circular oldini olish uchun
        from config import get_settings
        currency = get_settings().currency_symbol
    return f"{Decimal(amount):,.0f} {currency}".replace(",", " ")


def _ensure_foods_dir() -> None:
    FOODS_DIR.mkdir(parents=True, exist_ok=True)


async def save_food_photo(bot: Bot, telegram_file_id: str) -> str:
    """Telegram'dan rasmni yuklab, diskka saqlaydi va loyihaga nisbatan path qaytaradi.

    Path keyin DB'ga `Food.image_file_id` ustunida saqlanadi (ustun nomi tarixiy
    sabablarga ko'ra eski, lekin endi u file_id emas, balki disk path).
    """
    _ensure_foods_dir()
    name = f"{uuid.uuid4().hex}.jpg"
    abs_path = FOODS_DIR / name
    await bot.download(telegram_file_id, destination=str(abs_path))
    # Loyihaga nisbatan path — portable bo'lsin uchun.
    return str(abs_path.relative_to(MEDIA_ROOT.parent)).replace("\\", "/")


def resolve_food_photo(value: Optional[str]) -> Optional[FSInputFile]:
    """`Food.image_file_id` ustunidan FSInputFile qaytaradi (yoki None).

    Eski yozuvlarda bu ustunda Telegram file_id bo'lishi mumkin (cross-bot
    ishlamaydi). Agar diskda fayl topilmasa — None qaytaramiz va chaqiruvchi
    rasmsiz matn yuboradi.
    """
    if not value:
        return None
    # Project root'ga nisbatan path
    abs_path = MEDIA_ROOT.parent / value
    if abs_path.is_file():
        return FSInputFile(str(abs_path))
    return None


def delete_food_photo(value: Optional[str]) -> None:
    """Disk'dan rasmni o'chiradi. Xatolarni jimgina yutamiz (best-effort)."""
    if not value:
        return
    try:
        abs_path = MEDIA_ROOT.parent / value
        if abs_path.is_file():
            os.remove(abs_path)
    except OSError as e:
        log.warning("Rasmni o'chirib bo'lmadi (%s): %s", value, e)


def food_card_text(food, *, in_cart: int = 0, show_status: bool = False, prompt: str | None = None) -> str:
    """Mahsulot kartochkasi matni — ham customer, ham admin tomon ishlatadi.

    - `in_cart > 0` bo'lsa, "Savatchada N dona" satrini qo'shadi (customer flow).
    - `show_status=True` bo'lsa, mavjudlik holatini qo'shadi (admin flow).
    - `prompt` (masalan, "Miqdorni kiriting") oxirga qo'shiladi.
    """
    parts: list[str] = [f"<b>{food.name}</b>"]
    desc = (food.description or "").strip()
    if desc:
        parts.append(desc)
    parts.append(f"Narxi: {fmt_money(food.price)}")
    # Per-mahsulot minimal buyurtma — mijoz va admin kartalarida ko'rinadi.
    min_q = int(getattr(food, "min_quantity", 1) or 1)
    if min_q > 1:
        parts.append(f"Minimal buyurtma: <b>{min_q} dona</b>")
    if in_cart > 0:
        parts.append(f"🛒 Savatchada: <b>{in_cart} dona</b>")
    if show_status:
        status = "✅ mavjud" if food.is_available else "⛔️ o'chirilgan"
        parts.append(f"Holati: {status}")
    if prompt:
        parts.append(prompt)
    return "\n\n".join(parts)


async def send_food_card(
    message: Message,
    *,
    image_value: Optional[str],
    text: str,
    reply_markup=None,
) -> None:
    """Mahsulot kartasini yuborish — rasm bo'lsa rasm bilan, aks holda matn.

    Agar rasm DB'da yozilgan-u, lekin diskda topilmasa yoki Telegram rad qilsa —
    botni qulatmasdan, jimgina matn versiyasiga tushib ketamiz.
    """
    photo = resolve_food_photo(image_value)
    if photo is not None:
        try:
            await message.answer_photo(photo, caption=text, reply_markup=reply_markup)
            return
        except TelegramAPIError as e:
            log.warning("Mahsulot rasmini yuborib bo'lmadi (%s): %s", image_value, e)
    await message.answer(text, reply_markup=reply_markup)
