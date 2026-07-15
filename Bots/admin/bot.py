from __future__ import annotations

import html
import logging
import uuid
from decimal import Decimal
from typing import Iterable, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardRemove

from Bots.admin.filters import AdminBotAccessFilter, AdminCallbackGuard, IsAdminFilter
from Bots.admin.keyboards import (
    BTN_CANCEL_ORDER,
    BTN_NEW_ORDER,
    admin_main_kb,
    cancel_only_kb,
    confirm_delete_kb,
    confirm_order_kb,
    courier_actions_kb,
    couriers_list_kb,
    edit_cancel_kb,
    food_actions_kb,
    foods_list_kb,
    operator_main_kb,
    products_picker_kb,
    request_location_kb,
    request_phone_kb,
    skip_desc_kb,
    skip_photo_kb,
)
from Bots.admin.states import FoodCreate, FoodEdit, FoodPriceEdit, OperatorOrder
from Bots.common import (
    delete_food_photo,
    fmt_money,
    food_card_text,
    register_error_handler,
    save_food_photo,
)
from Domain.constants import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, MAX_NOTE_LENGTH
from Domain.models.courier import Courier
from Domain.models.food import Food
from Service.courier_service import CourierService
from Service.exceptions import DomainError, ValidationError
from Service.food_service import FoodService
from Service.notification_service import NotificationService
from Service.operator_service import OperatorService
from Service.order_display import order_display_number
from Service.order_service import CartItem, NewOrderInput, OrderService
from Service.phone import normalize_phone_or_none
from Service.user_service import UserService

log = logging.getLogger(__name__)


def _food_card_text(food: Food) -> str:
    return food_card_text(food, show_status=True)


def _courier_label(courier: Courier | None) -> str:
    """Buyurtma ro'yxatida kuryerni aniq identifikatsiya qilish uchun.

    Bir xil ismli kuryerlar bo'lishi mumkin, shuning uchun ism bilan birga
    @username (agar bor bo'lsa) va Telegram ID ko'rsatiladi.
    """
    if courier is None:
        return "—"
    parts = [courier.full_name]
    extras = []
    if courier.username:
        extras.append(f"@{courier.username}")
    extras.append(f"ID: <code>{courier.telegram_id}</code>")
    parts.append(f"({', '.join(extras)})")
    return " ".join(parts)


def _courier_card_text(courier: Courier, *, today: int, month: int, year: int, total: int) -> str:
    status = "✅ Aktiv" if courier.is_active else "⛔️ Noaktiv"
    started = "✅ ha" if courier.has_started_bot else "❌ yo'q"
    username = f"@{courier.username}" if courier.username else "—"
    phone = (
        f"<a href='tel:{courier.phone_number}'>{courier.phone_number}</a>"
        if courier.phone_number else "<i>kiritilmagan</i>"
    )
    cash = courier.cash_balance or 0
    cash_line = (
        f"\n\n💵 <b>Qo'lidagi naqd:</b> {fmt_money(cash)} "
        f"<i>(hali topshirilmagan)</i>"
        if cash and float(cash) > 0 else ""
    )
    return (
        f"<b>{courier.full_name}</b>\n"
        f"Username: {username}\n"
        f"Telefon: {phone}\n"
        f"Telegram ID: <code>{courier.telegram_id}</code>\n"
        f"Holati: {status}\n"
        f"Botga /start bosgan: {started}\n\n"
        f"<b>Yetkazib bergan zakazlari:</b>\n"
        f"• Bugun: <b>{today}</b>\n"
        f"• Shu oyda: <b>{month}</b>\n"
        f"• Shu yilda: <b>{year}</b>\n"
        f"• Hammasi: <b>{total}</b>"
        f"{cash_line}"
    )


def build_admin_dispatcher(
    *,
    food_service: FoodService,
    order_service: OrderService,
    courier_service: CourierService,
    user_service: UserService,
    notification_service: NotificationService,
    admin_telegram_ids: Iterable[int],
    operator_service: OperatorService,
    webapp_public_url: Optional[str] = None,
) -> Dispatcher:
    """Admin bot dispatcher.

    Uch xil foydalanuvchi:
      * admin    — to'liq huquq (env whitelist), Mahsulotlar/Kuryerlar CRUD
      * operator — DB'dagi AKTIV qator: `📞 Yangi buyurtma` FSM + Mini App
      * notanish — /start bossa noaktiv operator sifatida ro'yxatga olinadi
                   (kuryer bot patterni); admin aktivlashtirgach kira oladi.

    `webapp_public_url` berilsa, Mini App tugmasi ko'rinadi.
    """
    dp = Dispatcher(storage=MemoryStorage())
    register_error_handler(dp, "admin_bot")
    admin_ids = set(int(x) for x in admin_telegram_ids)

    # Kirish nazorati (default deny):
    #   1) AdminBotAccessFilter — admin YOKI aktiv operator; notanishga faqat /start.
    #   2) AdminCallbackGuard — `adm:*` callback'lar (mahsulot/kuryer/buyurtma
    #      boshqaruvi) faqat admin. Operator tugma matnini qo'lda tersa ham
    #      admin-only message handler'lar `admin_only` filtri bilan yopiq.
    access = AdminBotAccessFilter(admin_ids, operator_service)
    dp.message.filter(access)
    dp.callback_query.filter(access)
    dp.callback_query.filter(AdminCallbackGuard(admin_ids))
    admin_only = IsAdminFilter(admin_ids)

    def _main_kb():
        return admin_main_kb(webapp_public_url)

    def _operator_kb():
        return operator_main_kb()

    def _role_kb(tg_id: int):
        """Foydalanuvchi rolga mos klaviatura (access filtri o'tgan userlar uchun)."""
        return _main_kb() if tg_id in admin_ids else _operator_kb()

    @dp.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext) -> None:
        await state.clear()
        tg_id = message.from_user.id
        if tg_id in admin_ids:
            greet = "👋 <b>Admin paneliga xush kelibsiz!</b>"
            if webapp_public_url:
                greet += (
                    "\n\n🌐 To'liq dashboard'ni ochish uchun pastki chap burchakdagi "
                    "<b>Menu</b> tugmasini bosing."
                )
            await message.answer(greet, reply_markup=_main_kb())
            return

        # Operator yoki nomzod — DB'dan tekshiramiz (kuryer bot patterni).
        full_name = (message.from_user.full_name or "").strip()
        username = message.from_user.username
        op, created = await operator_service.get_or_register(
            tg_id, full_name, username, mark_started=True,
        )
        if created:
            # Adminlarga DM — yangi nomzod aktivlashtirishni kutmoqda
            # (best-effort: admin botga /start bosmagan bo'lsa DM bormaydi).
            # full_name — foydalanuvchi kiritadigan matn: HTML-escape SHART
            # (aks holda "<" li ism parse_mode=HTML'ni sindirib, xabar
            # BARCHA adminlarga bormay qolardi). username xavfsiz ([A-Za-z0-9_]).
            uname = f" (@{username})" if username else ""
            safe_name = html.escape(full_name) if full_name else f"#{tg_id}"
            alert = (
                f"🆕 <b>Yangi operator nomzodi</b>\n"
                f"👤 {safe_name}{uname}\n"
                f"🆔 <code>{tg_id}</code>\n\n"
                f"Aktivlashtirish: Admin paneli → <b>Operatorlar</b> bo'limi."
            )
            for admin_id in admin_ids:
                try:
                    await message.bot.send_message(chat_id=admin_id, text=alert)
                except TelegramAPIError as e:
                    log.warning("Adminga (tg=%s) yangi-operator xabari bormadi: %s", admin_id, e)
        if op.is_active:
            greet = (
                "👋 <b>Operator paneliga xush kelibsiz!</b>\n\n"
                "Mijoz bilan telefon orqali gaplashganingizda, uning buyurtmasini "
                "shu bot orqali tizimga kiritasiz. Buyurtma kuryerlar guruhiga "
                "tushadi va yetkazib beriladi."
            )
            if webapp_public_url:
                greet += (
                    "\n\n🌐 <b>«Yangi buyurtma»</b> sahifasini ochish uchun pastki chap "
                    "burchakdagi <b>Menu</b> tugmasini bosing."
                )
            await message.answer(greet, reply_markup=_operator_kb())
        else:
            # Yangi ro'yxatga olindi yoki hali aktivlashtirilmagan.
            await message.answer(
                "📋 <b>Operator sifatida ro'yxatga olindingiz.</b>\n\n"
                "Hisobingiz hali <b>aktivlashtirilmagan</b> — admin sizni "
                "«Operatorlar» bo'limidan aktiv qilib qo'ygach, /start ni "
                "qaytadan bosing va ishni boshlang.",
                reply_markup=ReplyKeyboardRemove(),
            )

    # ==================================================================
    # 📞 YANGI BUYURTMA — chat orqali FSM oqimi (operator + admin uchun)
    # ==================================================================
    #
    # Oqim sodda — mijoz qo'ng'iroq qilganda operator zudlik bilan buyurtmani
    # tizimga kiritsin:
    #
    #   1. PHONE       — mijoz telefoni (text, "+998901234567")
    #   2. NAME        — yangi mijoz uchun ism (eski mijozlar skip qilinadi)
    #   3. LOCATION    — yetkazib berish lokatsiyasi (forward qilingan yoki share)
    #   4. DETAILS     — manzil tafsilotlari (podyezd, kvartira)
    #   5. PRODUCTS    — mahsulotlar inline kb orqali
    #   6. NOTE        — buyurtmaga izoh
    #   7. CONFIRM     — yakuniy ko'rib chiqish va tasdiqlash
    #
    # Har step'da: BTN_CANCEL_ORDER ("❌ Bekor qilish") bosilsa — oqim
    # to'xtaydi, state tozalanadi, asosiy menyuga qaytadi.
    # ==================================================================

    async def _op_cancel(
        message: Message, state: FSMContext, actor_id: int | None = None,
    ) -> None:
        """Buyurtma yaratish oqimini bekor qiladi va asosiy menyuga qaytaradi.

        `actor_id` — haqiqiy foydalanuvchi ID'si. Callback'dan chaqirilganda
        MAJBURIY: `cb.message.from_user` — BOTNING o'zi, admin_ids'da yo'q,
        shuning uchun aktorsiz admin ham operator klaviaturasini olib qolardi.
        """
        await state.clear()
        uid = actor_id if actor_id is not None else message.from_user.id
        await message.answer(
            "❌ Buyurtma yaratish bekor qilindi.",
            reply_markup=_role_kb(uid),
        )

    # Har qanday state'da "❌ Bekor qilish" tugmasi ishlashi uchun universal handler.
    @dp.message(OperatorOrder(), F.text == BTN_CANCEL_ORDER)
    async def op_cancel_any(message: Message, state: FSMContext) -> None:
        await _op_cancel(message, state)

    # ---------------------- Entry: "📞 Yangi buyurtma" ----------------------

    @dp.message(F.text == BTN_NEW_ORDER)
    @dp.message(Command("new_order"))
    async def op_start(message: Message, state: FSMContext) -> None:
        await state.clear()
        await state.update_data(op_cart={}, op_data={})
        await message.answer(
            "📞 <b>Yangi buyurtma — 1/7</b>\n\n"
            "Mijozning <b>telefon raqamini</b> yozing.\n"
            "Format: <code>+998901234567</code>\n\n"
            "💡 <i>Mijoz Telegram'da o'z kontaktini ulashgan bo'lsa, shu kontaktni botga "
            "forward qilishingiz ham mumkin.</i>",
            reply_markup=request_phone_kb(),
        )
        await state.set_state(OperatorOrder.waiting_phone)

    # ---------------------- 1. PHONE ----------------------

    @dp.message(OperatorOrder.waiting_phone, F.contact)
    async def op_phone_contact(message: Message, state: FSMContext) -> None:
        """Forward yoki shared contact — telefoni avtomatik ajratiladi.

        Eslatma: operator boshqa odamning contact'ini forward qilishi mumkin
        (mijozdan kelgan). Bu OK — biz unga ishonamiz (faqat operator/admin
        bu oqimga kira oladi).
        """
        await _op_set_phone(message, state, message.contact.phone_number)

    @dp.message(OperatorOrder.waiting_phone, F.text)
    async def op_phone_text(message: Message, state: FSMContext) -> None:
        await _op_set_phone(message, state, message.text.strip())

    async def _op_set_phone(message: Message, state: FSMContext, raw_phone: str) -> None:
        """Telefonni tekshirib, mijozni qidiradi.

        Mavjud bo'lsa — to'g'ridan-to'g'ri LOCATION step'iga (NAME skip).
        Yo'q bo'lsa — NAME step'iga.

        Telefon shu yerda darhol validate qilinadi (E.164: 9-15 raqam, ixtiyoriy +).
        Format noto'g'ri bo'lsa — foydalanuvchidan qaytadan so'raymiz (yakuniy
        confirm step'gacha noto'g'ri ma'lumotni eltmaymiz).
        """
        # Yagona +998-normalizatsiya (Service/phone.py): '901234567' →
        # '+998901234567'. Noto'g'ri format — qaytadan so'raymiz.
        cleaned = normalize_phone_or_none(raw_phone)
        if cleaned is None:
            await message.answer(
                "❗️ Telefon raqam noto'g'ri formatda. Masalan: <code>+998901234567</code> "
                "yoki <code>901234567</code>"
            )
            return

        # Telegram contact ba'zan +'siz keladi — biz qo'shdik. Endi UserService
        # validatsiyasiga ishonamiz.
        try:
            db_user = await user_service.get_by_phone(cleaned)
        except Exception:
            # Ichki xato matni chatga oqmasin (SQL/traceback tafsilotlari) —
            # log'da to'liq, foydalanuvchiga umumiy xabar.
            log.exception("Mijozni telefon orqali topib bo'lmadi")
            await message.answer("❗️ Server xatosi yuz berdi. Birozdan so'ng qayta urinib ko'ring.")
            return

        data = await state.get_data()
        op_data = dict(data.get("op_data") or {})
        op_data["customer_phone"] = cleaned

        if db_user is not None and not db_user.is_deleted:
            op_data["customer_full_name"] = db_user.full_name
            op_data["customer_existing"] = True
            await state.update_data(op_data=op_data)
            await message.answer(
                f"✅ <b>Eski mijoz topildi:</b> {db_user.full_name}\n"
                f"📞 {db_user.phone_number}\n\n"
                f"📞 <b>2/7 — O'tkazib yuborildi</b> (ism allaqachon bor)\n\n"
                f"📍 <b>3/7 — Yetkazib berish manzili</b>\n"
                f"Mijoz Telegram'da yuborgan lokatsiyani shu botga <b>forward qiling</b>.",
                reply_markup=request_location_kb(),
            )
            await state.set_state(OperatorOrder.waiting_location)
        else:
            op_data["customer_existing"] = False
            await state.update_data(op_data=op_data)
            await message.answer(
                f"❗️ <b>{cleaned}</b> raqami bilan mijoz topilmadi — yangi mijoz.\n\n"
                "📞 <b>2/7 — Mijozning ismini</b> yozing:",
                reply_markup=cancel_only_kb(),
            )
            await state.set_state(OperatorOrder.waiting_name)

    # ---------------------- 2. NAME (yangi mijoz uchun) ----------------------

    @dp.message(OperatorOrder.waiting_name, F.text)
    async def op_name(message: Message, state: FSMContext) -> None:
        name = (message.text or "").strip()
        if len(name) < 2:
            await message.answer("❗️ Ism juda qisqa. Iltimos, to'liq ismni yozing.")
            return
        data = await state.get_data()
        op_data = dict(data.get("op_data") or {})
        op_data["customer_full_name"] = name
        await state.update_data(op_data=op_data)
        await message.answer(
            f"📍 <b>3/7 — Yetkazib berish manzili</b>\n"
            f"Mijoz Telegram'da yuborgan lokatsiyani shu botga <b>forward qiling</b>.",
            reply_markup=request_location_kb(),
        )
        await state.set_state(OperatorOrder.waiting_location)

    # ---------------------- 3. LOCATION ----------------------

    @dp.message(OperatorOrder.waiting_location, F.location)
    async def op_location(message: Message, state: FSMContext) -> None:
        lat = float(message.location.latitude)
        lon = float(message.location.longitude)
        # Sanity check — koordinata global chegaralarda
        if not (LAT_MIN <= lat <= LAT_MAX) or not (LON_MIN <= lon <= LON_MAX):
            await message.answer("❗️ Lokatsiya koordinatalari noto'g'ri. Qaytadan yuboring.")
            return
        data = await state.get_data()
        op_data = dict(data.get("op_data") or {})
        op_data["latitude"] = lat
        op_data["longitude"] = lon
        await state.update_data(op_data=op_data)
        await message.answer(
            f"✅ Lokatsiya qabul qilindi: <code>{lat:.5f}, {lon:.5f}</code>\n\n"
            f"🏠 <b>4/7 — Manzil tafsilotlari</b>\n"
            f"Podyezd, kvartira, eshik kodi va h.k. (yo'q bo'lsa <code>-</code> yuboring):",
            reply_markup=cancel_only_kb(),
        )
        await state.set_state(OperatorOrder.waiting_details)

    @dp.message(OperatorOrder.waiting_location)
    async def op_location_invalid(message: Message) -> None:
        await message.answer(
            "❗️ Iltimos, faqat <b>lokatsiya</b> yuboring — mijoz Telegram'da "
            "yuborgan lokatsiyani shu botga forward qiling.",
            reply_markup=request_location_kb(),
        )

    # ---------------------- 4. ADDRESS DETAILS ----------------------

    @dp.message(OperatorOrder.waiting_details, F.text)
    async def op_details(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        # "-" yoki "skip" — bo'sh deb hisoblaymiz
        details = "" if text in ("-", "skip", "Skip", "—") else text
        if len(details) > 200:
            await message.answer("❗️ Tafsilot juda uzun (200 belgidan ko'p emas). Qisqartiring.")
            return
        data = await state.get_data()
        op_data = dict(data.get("op_data") or {})
        op_data["address_details"] = details
        await state.update_data(op_data=op_data, op_cart={})

        # Endi mahsulotlarni ko'rsatamiz
        foods = await food_service.list_menu()
        if not foods:
            await message.answer(
                "❗️ Tizimda aktiv mahsulot yo'q. Avval admin'dan mahsulot qo'shishni so'rang.",
                reply_markup=_role_kb(message.from_user.id),
            )
            await state.clear()
            return
        await message.answer(
            "🛒 <b>5/7 — Mahsulot tanlash</b>\n"
            "Har mahsulot uchun <b>➕ / ➖</b> tugmalarini bosing. "
            "Tugagach <b>✅ Tugatdim</b> bosing.",
            reply_markup=ReplyKeyboardRemove(),
        )
        # Reply keyboard'ni olib tashlab, inline keyboard yuboramiz.
        # Picker xabarini saqlaymiz — keyin edit qilamiz har o'zgarishda.
        picker_msg = await message.answer(
            _op_cart_text({}, foods),
            reply_markup=products_picker_kb(foods, {}),
        )
        await state.update_data(
            op_data=op_data,
            op_cart={},
            op_picker_msg_id=picker_msg.message_id,
        )
        await state.set_state(OperatorOrder.waiting_products)

    # ---------------------- 5. PRODUCTS ----------------------

    def _op_cart_text(cart: dict, foods) -> str:
        """Mahsulot picker xabari uchun matn — joriy savatcha ko'rinishi."""
        if not cart:
            return (
                "🛒 <b>Savatcha bo'sh</b>\n\n"
                "Pastdagi tugmalardan mahsulot tanlang."
            )
        lines = ["🛒 <b>Savatcha:</b>\n"]
        total = Decimal("0.00")
        total_qty = 0
        for food in foods:
            qty = cart.get(food.id, 0)
            if qty <= 0:
                continue
            line_total = food.price * qty
            total += line_total
            total_qty += qty
            lines.append(f"• {food.name} × {qty} = {fmt_money(line_total)}")
        lines.append(f"\n<b>Jami:</b> {fmt_money(total)} ({total_qty} ta)")
        return "\n".join(lines)

    async def _op_refresh_picker(
        bot: Bot, chat_id: int, msg_id: int, cart: dict, foods,
    ) -> None:
        """Picker xabarini yangilash — har + / − bosilganda chaqiriladi."""
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=_op_cart_text(cart, foods),
                reply_markup=products_picker_kb(foods, cart),
                disable_web_page_preview=True,
            )
        except TelegramBadRequest as e:
            if "not modified" not in str(e).lower():
                log.warning("Picker xabarini edit qilib bo'lmadi: %s", e)

    @dp.callback_query(OperatorOrder.waiting_products, F.data.startswith("op:p:"))
    async def op_product_action(cb: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        action = cb.data.split(":")[2]
        data = await state.get_data()
        cart = {int(k): int(v) for k, v in (data.get("op_cart") or {}).items()}
        msg_id = data.get("op_picker_msg_id")

        if action == "cancel":
            await cb.answer()
            await _op_cancel(cb.message, state, actor_id=cb.from_user.id)
            return

        if action == "done":
            if not cart:
                await cb.answer("❗️ Avval mahsulot tanlang", show_alert=True)
                return
            # Cart finalize — kontakt telefon step'iga o'tamiz
            op_data = dict(data.get("op_data") or {})
            customer_phone = op_data.get("customer_phone", "")
            await cb.answer()
            await cb.message.answer(
                f"📞 <b>6/7 — Aloqa telefoni</b>\n"
                f"Kuryer mijoz bilan bog'lanish uchun raqam.\n\n"
                f"💡 <i>Mijoz raqami (<code>{customer_phone}</code>) bilan bir xil bo'lsa, "
                f"<code>=</code> yoki <code>same</code> yuboring.</i>",
                reply_markup=cancel_only_kb(),
            )
            await state.set_state(OperatorOrder.waiting_contact_phone)
            return

        if action in ("inc", "dec"):
            try:
                food_id = int(cb.data.split(":")[3])
            except (ValueError, IndexError):
                await cb.answer()
                return
            # Per-mahsulot minimal: 0 → birinchi "+" min'ga sakraydi; "−" min
            # ostiga tushsa — 0 (olib tashlash). Picker refresh uchun foods
            # baribir kerak — oldindan o'qib, min'ni ham shu yerdan olamiz.
            foods = await food_service.list_menu()
            food = next((f for f in foods if f.id == food_id), None)
            min_q = int(getattr(food, "min_quantity", 1) or 1) if food else 1
            cur = cart.get(food_id, 0)
            if action == "inc":
                cur = min_q if cur < min_q else min(cur + 1, 999)
            else:
                cur = cur - 1
                if cur < min_q:
                    cur = 0
            if cur == 0:
                cart.pop(food_id, None)
            else:
                cart[food_id] = cur
            await state.update_data(op_cart=cart)
            if msg_id is not None:
                await _op_refresh_picker(bot, cb.message.chat.id, msg_id, cart, foods)
            await cb.answer()
            return

        # info — kelajakda mahsulot tafsilotini ko'rsatish mumkin
        await cb.answer()

    # ---------------------- 6. CONTACT PHONE ----------------------

    @dp.message(OperatorOrder.waiting_contact_phone, F.text)
    async def op_contact_phone(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        op_data = dict(data.get("op_data") or {})
        text = (message.text or "").strip()

        # `=` yoki `same` — mijoz telefoni bilan bir xil (allaqachon normalizatsiyalangan)
        if text in ("=", "same", "Same"):
            contact = op_data.get("customer_phone", "")
        else:
            # +998 avto-normalizatsiya; tushunarsiz format — qaytadan so'raymiz.
            contact = normalize_phone_or_none(text)
            if contact is None:
                await message.answer(
                    "❗️ Telefon raqam noto'g'ri formatda. Masalan: "
                    "<code>+998901234567</code> yoki <code>901234567</code>. "
                    "Mijoz raqami bilan bir xil bo'lsa <code>=</code> yozing."
                )
                return
        if len(contact) < 4:
            await message.answer("❗️ Telefon raqam juda qisqa. Qaytadan yozing.")
            return
        op_data["contact_phone"] = contact
        await state.update_data(op_data=op_data)
        await message.answer(
            "📝 <b>7/7 — Izoh</b>\n"
            "Kuryer va oshpaz uchun maxsus ko'rsatma "
            "(masalan: \"qo'ng'iroq qilmasdan tashlab keting\"):",
            reply_markup=cancel_only_kb(),
        )
        await state.set_state(OperatorOrder.waiting_note)

    # ---------------------- 7. NOTE ----------------------

    @dp.message(OperatorOrder.waiting_note, F.text)
    async def op_note(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text:
            await message.answer("❗️ Izoh bo'sh bo'lishi mumkin emas. Qisqa izoh yozing.")
            return
        if len(text) > MAX_NOTE_LENGTH:
            await message.answer(f"❗️ Izoh juda uzun ({MAX_NOTE_LENGTH} belgidan ko'p emas).")
            return
        data = await state.get_data()
        op_data = dict(data.get("op_data") or {})
        op_data["note"] = text
        await state.update_data(op_data=op_data)
        await _op_show_confirm(message, state)

    # ---------------------- 7. CONFIRM ----------------------

    async def _op_show_confirm(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        op_data = dict(data.get("op_data") or {})
        cart = {int(k): int(v) for k, v in (data.get("op_cart") or {}).items()}
        foods = await food_service.list_menu()

        lines = ["📋 <b>Yakuniy ko'rib chiqish</b>\n"]
        lines.append(f"👤 <b>Mijoz:</b> {op_data.get('customer_full_name', '—')}")
        lines.append(f"📞 {op_data.get('customer_phone', '—')}")
        lines.append(f"📍 <code>{op_data.get('latitude'):.5f}, {op_data.get('longitude'):.5f}</code>")
        if op_data.get("address_details"):
            lines.append(f"🏠 {op_data['address_details']}")
        lines.append("\n<b>Mahsulotlar:</b>")
        total = Decimal("0.00")
        for food in foods:
            qty = cart.get(food.id, 0)
            if qty <= 0:
                continue
            line_total = food.price * qty
            total += line_total
            lines.append(f"  • {food.name} × {qty} = {fmt_money(line_total)}")
        lines.append(f"\n💵 <b>Jami:</b> {fmt_money(total)} (naqd)")
        lines.append(f"☎️ Aloqa: {op_data.get('contact_phone', '—')}")
        if op_data.get("note"):
            lines.append(f"📝 {op_data['note']}")
        await message.answer(
            "\n".join(lines),
            reply_markup=ReplyKeyboardRemove(),
        )
        await message.answer(
            "Buyurtmani yuborishni tasdiqlaysizmi?",
            reply_markup=confirm_order_kb(),
        )
        # Idempotency kaliti confirm KO'RSATILGANDA yaratiladi — "✅ Ha" ikki
        # marta (parallel task'larda) bosilsa ham ikkalasi BIR XIL kalit bilan
        # create_order'ga boradi va bitta buyurtma qaytadi (mijoz boti naqshi).
        op_data["op_idem_key"] = uuid.uuid4().hex
        await state.update_data(op_data=op_data)
        await state.set_state(OperatorOrder.confirming)

    @dp.callback_query(OperatorOrder.confirming, F.data == "op:confirm:no")
    async def op_confirm_no(cb: CallbackQuery, state: FSMContext) -> None:
        await cb.answer()
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        await _op_cancel(cb.message, state, actor_id=cb.from_user.id)

    @dp.callback_query(OperatorOrder.confirming, F.data == "op:confirm:yes")
    async def op_confirm_yes(cb: CallbackQuery, state: FSMContext) -> None:
        await cb.answer()
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass

        data = await state.get_data()
        op_data = dict(data.get("op_data") or {})
        cart = {int(k): int(v) for k, v in (data.get("op_cart") or {}).items()}
        if not cart:
            await cb.message.answer("❗️ Savatcha bo'sh — buyurtma yaratib bo'lmadi.")
            await _op_cancel(cb.message, state, actor_id=cb.from_user.id)
            return

        # 1) Mijozni topish/yaratish
        try:
            customer = await user_service.find_or_create_for_operator(
                full_name=op_data.get("customer_full_name", ""),
                phone_number=op_data.get("customer_phone", ""),
            )
        except DomainError as e:
            await cb.message.answer(f"❗️ {e}")
            await _op_cancel(cb.message, state, actor_id=cb.from_user.id)
            return

        # 2) Buyurtma yaratish — idempotency kaliti confirm ko'rsatilganda
        # yaratilgan (op_idem_key): "✅ Ha" ikki marta bosilsa ham bitta buyurtma.
        items = [CartItem(food_id=fid, quantity=qty) for fid, qty in cart.items()]
        try:
            order = await order_service.create_order(NewOrderInput(
                customer_telegram_id=customer.telegram_id,
                items=items,
                delivery_latitude=float(op_data.get("latitude", 0.0)),
                delivery_longitude=float(op_data.get("longitude", 0.0)),
                contact_phone=op_data.get("contact_phone", ""),
                note=op_data.get("note", ""),
                idempotency_key=op_data.get("op_idem_key"),
                address_label="",
                address_details=op_data.get("address_details", ""),
                created_by_operator_id=int(cb.from_user.id),
            ))
        except DomainError as e:
            await cb.message.answer(f"❗️ {e}")
            await _op_cancel(cb.message, state, actor_id=cb.from_user.id)
            return

        # 3) Kuryer guruhiga yuborish (best-effort)
        try:
            msg_id = await notification_service.dispatch_to_couriers_group(order)
            if msg_id is not None:
                await order_service.attach_group_message(order.id, msg_id)
        except (TelegramAPIError, OSError) as e:
            log.warning("Operator buyurtmasi (#%s) guruhiga yuborilmadi: %s", order.id, e)
        try:
            await notification_service.notify_couriers_new_order(order)
        except Exception as e:
            log.warning("Kuryerlarga DM bildirishnoma yuborilmadi #%s: %s", order.id, e)

        # 4) Mijozga DM (faqat has_started_bot=True bo'lsa — service ichida tekshiruv)
        try:
            customer_msg_id = await notification_service.upsert_customer_status_message(order)
            if customer_msg_id is not None:
                await order_service.attach_customer_dm_message(order.id, customer_msg_id)
        except (TelegramAPIError, OSError) as e:
            log.warning("Mijozga DM yuborilmadi (#%s): %s", order.id, e)

        await state.clear()
        await cb.message.answer(
            f"✅ <b>Buyurtma {order_display_number(order)} yaratildi</b>\n"
            f"💵 Jami: {fmt_money(order.total_amount)} (naqd)\n"
            f"🚗 Kuryerlar guruhiga yuborildi.",
            reply_markup=_role_kb(cb.from_user.id),
        )

    # ==================================================================
    # /Yangi buyurtma oqimi tugadi
    # ==================================================================

    @dp.message(F.text == "ℹ️ Yordam")
    async def operator_help(message: Message) -> None:
        # Access filtridan o'tgan admin bo'lmagan user = aktiv operator.
        if message.from_user.id in admin_ids:
            return
        await message.answer(
            "<b>Yordam — Operator</b>\n\n"
            "Buyurtma kiritishning 2 yo'li bor:\n\n"
            "<b>A. Chat orqali</b> (📞 Yangi buyurtma tugmasi)\n"
            "  1. Mijoz Telegram'da lokatsiyasini yuborsa — uni shu botga forward qiling.\n"
            "  2. Bot qadam-baqadam savol beradi (telefon → ism → lokatsiya → mahsulotlar → izoh).\n"
            "  3. Oxirida tasdiqlasangiz, kuryerlar guruhiga ketadi.\n\n"
            "<b>B. Mini App orqali</b> (Menu → Yangi buyurtma)\n"
            "  Grafik forma — xaritada qidirish bilan, qo'lda lokatsiya tanlash mumkin.",
            reply_markup=_operator_kb(),
        )

    # ---------------------- Edit-in-place helper ----------------------

    async def _smart_edit(
        message: Message,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> None:
        """Xabarni yangi yubormasdan tahrirlaydi:
        - matn xabari bo'lsa: `edit_text`
        - rasm xabari bo'lsa: `edit_caption`
        Edit imkonsiz (48+ soat, o'chirilgan) — eski xabarni delete qilib,
        yangisini yuboramiz (admin sukut bilan stuck bo'lib qolmaslik uchun).
        """
        try:
            if message.photo or message.video or message.animation:
                await message.edit_caption(caption=text, reply_markup=reply_markup)
            else:
                await message.edit_text(
                    text, reply_markup=reply_markup, disable_web_page_preview=True,
                )
            return
        except TelegramBadRequest as e:
            err = str(e).lower()
            if "not modified" in err:
                return
            # 48 soat o'tdi, yoki xabar o'chirilgan — eski'ni delete, yangi yuboramiz.
            log.info("admin _smart_edit: edit fail (%s) — fallback to delete+resend", e)
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        try:
            await message.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)
        except TelegramBadRequest as e:
            log.warning("admin _smart_edit fallback ham ishlamadi: %s", e)

    # ---------------------- Mahsulotlar ro'yxati ----------------------

    @dp.message(F.text == "💧 Mahsulotlar", admin_only)
    @dp.message(Command("foods"), admin_only)
    async def list_foods(message: Message, state: FSMContext) -> None:
        # FoodCreate/FoodEdit oqimida bo'lsak, "Mahsulotlar" bosish — abort
        await state.clear()
        foods = await food_service.list_all()
        await message.answer("💧 <b>Mahsulotlar:</b>", reply_markup=foods_list_kb(foods))

    @dp.callback_query(F.data == "noop")
    async def cb_noop(cb: CallbackQuery) -> None:
        await cb.answer()

    @dp.callback_query(F.data == "adm:foods")
    async def back_to_foods(cb: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        foods = await food_service.list_all()
        await _smart_edit(cb.message, "💧 <b>Mahsulotlar:</b>", foods_list_kb(foods))
        await cb.answer()

    @dp.callback_query(F.data.startswith("adm:food:"))
    async def open_food(cb: CallbackQuery, state: FSMContext) -> None:
        food_id = int(cb.data.split(":")[2])
        try:
            food = await food_service.get(food_id)
        except DomainError as e:
            await cb.answer(str(e), show_alert=True)
            return
        await state.clear()  # tahrirlash oqimidan chiqamiz
        await _smart_edit(cb.message, _food_card_text(food), food_actions_kb(food))
        await cb.answer()

    # ---------------------- Toggle / Delete ----------------------

    @dp.callback_query(F.data.startswith("adm:toggle:"))
    async def toggle_food(cb: CallbackQuery) -> None:
        food_id = int(cb.data.split(":")[2])
        try:
            food = await food_service.get(food_id)
        except DomainError as e:
            await cb.answer(str(e), show_alert=True)
            return
        try:
            await food_service.update(food_id, is_available=not food.is_available)
        except DomainError as e:
            await cb.answer(str(e), show_alert=True)
            return
        food = await food_service.get(food_id)
        await _smart_edit(cb.message, _food_card_text(food), food_actions_kb(food))
        await cb.answer("✅ Yoqildi" if food.is_available else "⛔️ O'chirib qo'yildi")

    @dp.callback_query(F.data.startswith("adm:delete:"))
    async def confirm_delete(cb: CallbackQuery) -> None:
        food_id = int(cb.data.split(":")[2])
        try:
            food = await food_service.get(food_id)
        except DomainError as e:
            await cb.answer(str(e), show_alert=True)
            return
        text = (
            f"<b>{food.name}</b>\n\n"
            "Ushbu mahsulotni butunlay o'chirmoqchimisiz?\n"
            "Eski buyurtmalardagi tarix saqlanib qoladi."
        )
        await _smart_edit(cb.message, text, confirm_delete_kb(food_id))
        await cb.answer()

    @dp.callback_query(F.data.startswith("adm:delete_yes:"))
    async def do_delete(cb: CallbackQuery) -> None:
        food_id = int(cb.data.split(":")[2])
        # Avval rasmni eslab qolamiz, DB'dan o'chirgandan so'ng faylni ham tozalash uchun.
        try:
            food = await food_service.get(food_id)
        except DomainError as e:
            await cb.answer(str(e), show_alert=True)
            return
        old_image = food.image_file_id
        try:
            await food_service.delete(food_id)
        except DomainError as e:
            await cb.answer(str(e), show_alert=True)
            return
        except Exception as e:
            log.exception("Mahsulotni o'chirib bo'lmadi #%s", food_id)
            await cb.answer(f"Xatolik: {e}", show_alert=True)
            return
        delete_food_photo(old_image)
        # Mahsulotlar ro'yxatiga qaytamiz — yangi xabar yubormasdan.
        foods = await food_service.list_all()
        await _smart_edit(cb.message, "💧 <b>Mahsulotlar:</b>", foods_list_kb(foods))
        await cb.answer("🗑 O'chirildi")

    # ---------------------- Yangi mahsulot ----------------------

    @dp.message(F.text == "➕ Yangi mahsulot", admin_only)
    @dp.message(Command("new_food"), admin_only)
    async def new_food(message: Message, state: FSMContext) -> None:
        await state.set_state(FoodCreate.name)
        await message.answer("Yangi mahsulot nomini kiriting:")

    @dp.message(FoodCreate.name, F.text)
    async def new_food_name(message: Message, state: FSMContext) -> None:
        await state.update_data(name=message.text.strip())
        await state.set_state(FoodCreate.description)
        await message.answer(
            "Tavsifini kiriting (ixtiyoriy):",
            reply_markup=skip_desc_kb(),
        )

    @dp.callback_query(FoodCreate.description, F.data == "adm:new:nodesc")
    async def new_food_no_desc(cb: CallbackQuery, state: FSMContext) -> None:
        await state.update_data(description="")
        await state.set_state(FoodCreate.price)
        await cb.message.answer("Narxini kiriting (so'mda, masalan: 35000):")
        await cb.answer()

    @dp.message(FoodCreate.description, F.text)
    async def new_food_desc(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        # "-" eski usul bilan o'tkazib yuborish uchun ham qoldiramiz
        desc = "" if text == "-" else text
        await state.update_data(description=desc)
        await state.set_state(FoodCreate.price)
        await message.answer("Narxini kiriting (so'mda, masalan: 35000):")

    @dp.message(FoodCreate.price, F.text)
    async def new_food_price(message: Message, state: FSMContext) -> None:
        await state.update_data(price=message.text.strip())
        await state.set_state(FoodCreate.photo)
        await message.answer(
            "Endi mahsulot rasmini yuboring:",
            reply_markup=skip_photo_kb(),
        )

    @dp.callback_query(FoodCreate.photo, F.data == "adm:new:nophoto")
    async def new_food_no_photo(cb: CallbackQuery, state: FSMContext) -> None:
        await _commit_new_food(cb.message, state, image_path=None)
        await cb.answer()

    @dp.message(FoodCreate.photo, F.photo)
    async def new_food_with_photo(message: Message, state: FSMContext, bot: Bot) -> None:
        try:
            image_path = await save_food_photo(bot, message.photo[-1].file_id)
        except Exception:
            log.exception("Yangi mahsulot rasmini saqlab bo'lmadi")
            await message.answer(
                "❗️ Rasmni saqlashda xatolik. Qaytadan yuboring yoki rasmsiz davom eting.",
                reply_markup=skip_photo_kb(),
            )
            return
        await _commit_new_food(message, state, image_path=image_path)

    async def _commit_new_food(
        message: Message, state: FSMContext, image_path: str | None
    ) -> None:
        data = await state.get_data()
        try:
            food = await food_service.create(
                name=data.get("name", ""),
                description=data.get("description", ""),
                price=data.get("price"),
                image_file_id=image_path,
            )
        except ValidationError as e:
            # DB'ga yozilmadi — agar rasm allaqachon diskka tushgan bo'lsa, tozalaymiz.
            delete_food_photo(image_path)
            await message.answer(f"❗️ {e}\nQaytadan urinib ko'ring (➕ Yangi mahsulot).")
            await state.clear()
            return
        await state.clear()
        await message.answer(
            f"✅ Mahsulot qo'shildi: <b>{food.name}</b>",
            reply_markup=_main_kb(),
        )

    # ---------------------- Tahrirlash ----------------------
    # Bu yerda yangi xabar yubormaymiz: mavjud mahsulot kartochkasini
    # promptga aylantirib, foydalanuvchi javobini olganimizdan keyin yana
    # shu xabarni updated kartochkaga aylantiramiz.

    @dp.callback_query(F.data.startswith("adm:edit:"))
    async def start_edit(cb: CallbackQuery, state: FSMContext) -> None:
        _, _, field, food_id_s = cb.data.split(":")
        food_id = int(food_id_s)
        try:
            food = await food_service.get(food_id)
        except DomainError as e:
            await cb.answer(str(e), show_alert=True)
            return
        prompts = {
            "name":  f"<b>{food.name}</b>\n\nYangi <b>nomni</b> yozib yuboring:",
            "desc":  f"<b>{food.name}</b>\n\nYangi <b>tavsifni</b> yozib yuboring:",
            "price": f"<b>{food.name}</b>\n\nYangi <b>narxni</b> yozib yuboring (so'mda, masalan: 35000):",
            "photo": f"<b>{food.name}</b>\n\nYangi <b>rasmni</b> yuboring:",
        }
        await state.update_data(
            edit_food_id=food_id,
            edit_field=field,
            edit_msg_id=cb.message.message_id,
            edit_chat_id=cb.message.chat.id,
        )
        if field == "price":
            await state.set_state(FoodPriceEdit.value)
        else:
            await state.set_state(FoodEdit.field_value)
        await _smart_edit(cb.message, prompts[field], edit_cancel_kb(food_id))
        await cb.answer()

    @dp.message(FoodEdit.field_value, F.photo)
    async def edit_apply_photo(message: Message, state: FSMContext, bot: Bot) -> None:
        data = await state.get_data()
        if data.get("edit_field") != "photo":
            return
        food_id = data.get("edit_food_id")
        try:
            old = await food_service.get(int(food_id))
            old_image = old.image_file_id
        except DomainError:
            old_image = None
        try:
            new_path = await save_food_photo(bot, message.photo[-1].file_id)
        except Exception:
            log.exception("Mahsulot rasmini yangilab bo'lmadi (food_id=%s)", food_id)
            # Promptni qaytadan ko'rsatamiz, ammo yangi xabar yubormaymiz.
            return
        # User'ning yuborgan rasmini chatdan o'chiramiz (chat toza qolsin).
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        await _apply_edit(bot, state, image_file_id=new_path)
        delete_food_photo(old_image)

    @dp.message(FoodEdit.field_value, F.text)
    async def edit_apply_text(message: Message, state: FSMContext, bot: Bot) -> None:
        data = await state.get_data()
        field = data.get("edit_field")
        text = (message.text or "").strip()
        # User'ning text xabarini chatdan o'chiramiz — kartochka yagona bo'lib qoladi.
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        if field == "name":
            await _apply_edit(bot, state, name=text)
        elif field == "desc":
            await _apply_edit(bot, state, description=text)

    @dp.message(FoodPriceEdit.value, F.text)
    async def edit_apply_price(message: Message, state: FSMContext, bot: Bot) -> None:
        text = (message.text or "").strip()
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        await _apply_edit(bot, state, price=text)

    async def _apply_edit(bot: Bot, state: FSMContext, **kwargs) -> None:
        """Mahsulotni yangilab, mahsulot kartochkasi xabarini in-place tahrirlaydi."""
        data = await state.get_data()
        food_id = int(data.get("edit_food_id"))
        edit_msg_id = data.get("edit_msg_id")
        edit_chat_id = data.get("edit_chat_id")
        try:
            food = await food_service.update(food_id, **kwargs)
        except ValidationError as e:
            # Promptni xato matn bilan yangilaymiz (yangi xabar yubormaymiz).
            if edit_msg_id and edit_chat_id:
                try:
                    await bot.edit_message_text(
                        chat_id=edit_chat_id,
                        message_id=edit_msg_id,
                        text=f"❗️ {e}\n\nQaytadan yozing yoki ⬅️ Bekor:",
                        reply_markup=edit_cancel_kb(food_id),
                    )
                except TelegramBadRequest:
                    pass
            return
        except DomainError as e:
            # Masalan food_not_found — parallel sessiya mahsulotni o'chirgan.
            # Javobsiz qolib state osilib qolmasin: xabar + state tozalanadi.
            await state.clear()
            if edit_msg_id and edit_chat_id:
                try:
                    await bot.edit_message_text(
                        chat_id=edit_chat_id,
                        message_id=edit_msg_id,
                        text=f"❗️ {e}",
                        reply_markup=None,
                    )
                except TelegramBadRequest:
                    pass
            return
        await state.clear()
        if edit_msg_id and edit_chat_id:
            try:
                await bot.edit_message_text(
                    chat_id=edit_chat_id,
                    message_id=edit_msg_id,
                    text=_food_card_text(food),
                    reply_markup=food_actions_kb(food),
                )
            except TelegramBadRequest as e:
                # photo edit kerak bo'lsa, edit_message_caption sinab ko'ramiz
                if "no text" in str(e).lower() or "message can't be edited" in str(e).lower():
                    try:
                        await bot.edit_message_caption(
                            chat_id=edit_chat_id,
                            message_id=edit_msg_id,
                            caption=_food_card_text(food),
                            reply_markup=food_actions_kb(food),
                        )
                    except TelegramBadRequest:
                        log.info("Edit complete but card refresh failed for #%s", food_id)

    # ---------------------- Buyurtmalar ----------------------

    @dp.message(F.text == "📦 Buyurtmalar", admin_only)
    @dp.message(Command("orders"), admin_only)
    async def list_orders(message: Message) -> None:
        orders = await order_service.list_recent(limit=15)
        if not orders:
            await message.answer("Hozircha buyurtmalar yo'q.")
            return
        blocks = ["📦 <b>So'nggi buyurtmalar:</b>"]
        for o in orders:
            created = o.created_at.strftime("%d.%m.%Y %H:%M") if o.created_at else "—"
            blocks.append(
                f"\n🆔 <b>{order_display_number(o)}</b>\n"
                f"👤 Mijoz: {o.customer.full_name}\n"
                f"📞 Telefon: <code>{o.contact_phone}</code>\n"
                f"💵 Jami: {fmt_money(o.total_amount)}\n"
                f"📊 Holat: {o.status.label_uz}\n"
                f"🚗 Kuryer: {_courier_label(o.courier)}\n"
                f"📅 Sana: {created}"
            )
        await message.answer("\n".join(blocks), disable_web_page_preview=True)

    # ---------------------- Kuryerlar ----------------------

    @dp.message(F.text == "👤 Kuryerlar", admin_only)
    @dp.message(Command("couriers"), admin_only)
    async def list_couriers(message: Message) -> None:
        try:
            couriers = await courier_service.list_all()
        except Exception:
            log.exception("Kuryerlar ro'yxatini olib bo'lmadi")
            await message.answer("⚠️ Kuryerlar ro'yxatini yuklashda xatolik.")
            return
        if not couriers:
            await message.answer(
                "👤 <b>Kuryerlar:</b>\n\n"
                "Hozircha bironta kuryer botga /start bosmagan. "
                "Kuryerlar botga DM dan /start yuborgach, shu yerda paydo bo'lishadi."
            )
            return
        await message.answer(
            "👤 <b>Kuryerlar:</b>\n"
            "Kuryerni aktiv/noaktiv qilish va statistikasini ko'rish uchun ro'yxatdan tanlang.",
            reply_markup=couriers_list_kb(couriers),
        )

    @dp.callback_query(F.data == "adm:couriers")
    async def back_to_couriers(cb: CallbackQuery) -> None:
        couriers = await courier_service.list_all()
        await _smart_edit(cb.message, "👤 <b>Kuryerlar:</b>", couriers_list_kb(couriers))
        await cb.answer()

    @dp.callback_query(F.data.startswith("adm:cour:"))
    async def open_courier(cb: CallbackQuery) -> None:
        try:
            courier_id = int(cb.data.split(":")[2])
            courier = await courier_service.get(courier_id)
            stats = await order_service.delivered_stats_for_courier(courier.id)
        except DomainError as e:
            await cb.answer(str(e), show_alert=True)
            return
        except Exception:
            log.exception("Kuryer kartasini ochib bo'lmadi: %s", cb.data)
            await cb.answer("Xatolik yuz berdi. Adminga xabar bering.", show_alert=True)
            return
        text = _courier_card_text(
            courier, today=stats.today, month=stats.month, year=stats.year, total=stats.total,
        )
        await _smart_edit(cb.message, text, courier_actions_kb(courier))
        await cb.answer()

    @dp.callback_query(F.data.startswith("adm:cour_toggle:"))
    async def toggle_courier(cb: CallbackQuery) -> None:
        try:
            courier_id = int(cb.data.split(":")[2])
            courier = await courier_service.get(courier_id)
            courier = await courier_service.set_active(courier_id, not courier.is_active)
            stats = await order_service.delivered_stats_for_courier(courier.id)
        except DomainError as e:
            await cb.answer(str(e), show_alert=True)
            return
        except Exception:
            log.exception("Kuryerni toggle qilib bo'lmadi: %s", cb.data)
            await cb.answer("Xatolik yuz berdi.", show_alert=True)
            return
        text = _courier_card_text(
            courier, today=stats.today, month=stats.month, year=stats.year, total=stats.total,
        )
        await _smart_edit(cb.message, text, courier_actions_kb(courier))
        await cb.answer("✅ Aktiv" if courier.is_active else "⛔️ Noaktiv")

    return dp


def make_admin_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
