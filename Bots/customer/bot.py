from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    Contact,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from Bots.common import fmt_money, food_card_text, register_error_handler, send_food_card
from Bots.customer.keyboards import (
    BTN_BACK,
    BTN_CANCEL,
    BTN_CART,
    BTN_CHECKOUT,
    BTN_CLEAR_CART,
    BTN_CONFIRM,
    BTN_MY_ORDERS,
    BTN_PRODUCTS,
    cart_menu_kb,
    confirm_menu_kb,
    main_menu_kb,
    products_menu_kb,
    quantity_kb,
    request_location_kb,
    request_phone_kb,
)
from Bots.customer.states import Browsing, Checkout, Registration
from Domain.models.food import Food
from Service.exceptions import DomainError, ValidationError
from Service.food_service import FoodService
from Service.notification_service import NotificationService
from Service.order_display import order_display_number
from Service.order_service import CartItem, NewOrderInput, OrderService
from Service.user_service import RegistrationInput, UserService

log = logging.getLogger(__name__)

CART_KEY = "cart"  # FSM data["cart"] = {food_id: qty}
CURRENT_FOOD_KEY = "current_food_id"  # FSM data — hozir tanlangan mahsulot


def _get_cart(data: Dict[str, Any]) -> Dict[int, int]:
    cart = data.get(CART_KEY) or {}
    return {int(k): int(v) for k, v in cart.items()}


async def _save_cart(state: FSMContext, cart: Dict[int, int]) -> None:
    await state.update_data(**{CART_KEY: cart})


def _food_card_text(food: Food, in_cart: int) -> str:
    return food_card_text(food, in_cart=in_cart, prompt="Miqdorni kiriting")


def build_customer_dispatcher(
    *,
    user_service: UserService,
    food_service: FoodService,
    order_service: OrderService,
    notification_service: NotificationService,
    brand_name: str,
    webapp_url: Optional[str] = None,
) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    register_error_handler(dp, "customer_bot")

    def _main_kb():
        return main_menu_kb(webapp_url)

    # ---------------------- Yordamchilar ----------------------

    async def _go_main_menu(message: Message, state: FSMContext, *, greet: Optional[str] = None) -> None:
        # Asosiy menyuga qaytamiz: state'ni tozalamaymiz, lekin
        # Browsing/Checkout state'larini yo'q qilamiz, savatchani saqlaymiz.
        data = await state.get_data()
        cart = _get_cart(data)
        await state.set_state(None)
        await state.set_data({CART_KEY: cart})
        text = greet or f"<b>{brand_name}</b> xizmatingizda 💧"
        await message.answer(text, reply_markup=_main_kb())

    async def _show_products(message: Message, state: FSMContext) -> None:
        foods = await food_service.list_menu()
        await state.update_data(**{CURRENT_FOOD_KEY: None})
        await state.set_state(Browsing.products)
        if not foods:
            await message.answer(
                "Hozircha mahsulotlar yo'q.", reply_markup=_main_kb()
            )
            await state.set_state(None)
            return
        await message.answer(
            "💧 <b>Mahsulotlar</b>\nMahsulotni tanlang:",
            reply_markup=products_menu_kb(foods),
        )

    async def _render_cart(message: Message, state: FSMContext) -> None:
        cart = _get_cart(await state.get_data())
        if not cart:
            await message.answer(
                "🛒 Savatchangiz bo'sh.", reply_markup=_main_kb()
            )
            await state.set_state(None)
            return
        lines = ["🛒 <b>Savatcha</b>\n"]
        total = Decimal("0.00")
        for food_id, qty in cart.items():
            try:
                food = await food_service.get(food_id)
            except DomainError:
                continue
            line_total = food.price * qty
            total += line_total
            lines.append(f"• {food.name} × {qty} = {fmt_money(line_total)}")
        lines.append(f"\n<b>Jami:</b> {fmt_money(total)}")
        await state.set_state(Browsing.in_cart)
        await message.answer("\n".join(lines), reply_markup=cart_menu_kb())

    # ---------------------- "Mening buyurtmalarim" sahifalash ----------------------

    async def _build_orders_page(
        telegram_id: int, *, offset: int, page_size: int = 10,
    ) -> tuple[str, Optional[InlineKeyboardMarkup]]:
        """Bitta sahifa matni + ◀️ Oldingi / Keyingi ▶️ inline tugmalari.

        Sahifa bo'sh bo'lsa — `(matn, None)` qaytaradi (klaviatura yo'q).
        """
        total = await order_service.count_for_customer(telegram_id)
        if total == 0:
            return "Sizda hali buyurtmalar yo'q.", None

        # offset chegaradan oshmasin (oxirgi sahifaga to'g'rilash)
        if offset >= total:
            offset = max(0, (total - 1) // page_size * page_size)

        orders = await order_service.list_for_customer(
            telegram_id, limit=page_size, offset=offset,
        )
        shown_end = offset + len(orders)
        header = (
            f"📦 <b>Buyurtmalaringiz</b> "
            f"({offset + 1}–{shown_end} / {total})\n"
        )
        lines = [header]
        for o in orders:
            lines.append(
                f"{order_display_number(o)} — {fmt_money(o.total_amount)} — {o.status.label_uz}"
            )

        nav: list[InlineKeyboardButton] = []
        if offset > 0:
            nav.append(InlineKeyboardButton(
                text="◀️ Oldingi",
                callback_data=f"myorders:page:{max(0, offset - page_size)}",
            ))
        if shown_end < total:
            nav.append(InlineKeyboardButton(
                text="Keyingi ▶️",
                callback_data=f"myorders:page:{offset + page_size}",
            ))
        kb = InlineKeyboardMarkup(inline_keyboard=[nav]) if nav else None
        return "\n".join(lines), kb

    # ---------------------- /start + ro'yxatdan o'tish ----------------------

    @dp.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext) -> None:
        await state.clear()
        user = await user_service.get_by_telegram_id(message.from_user.id)
        if user:
            # has_started_bot=True bo'lib qo'yish — operator yaratgan, lekin keyin
            # bot orqali kelgan mijoz uchun ham (yangi DM xabar oqimi ochiladi).
            await user_service.mark_started_bot(message.from_user.id)
            await message.answer(
                f"Salom, {user.full_name}! 👋\n<b>{brand_name}</b> xizmatingizda.",
                reply_markup=_main_kb(),
            )
            return
        await message.answer(
            f"Assalomu alaykum! <b>{brand_name}</b> ning yetkazib berish xizmatiga "
            f"xush kelibsiz! 👋\n\nRo'yxatdan o'tish uchun ismingizni kiriting:"
        )
        await state.set_state(Registration.waiting_full_name)

    @dp.message(Registration.waiting_full_name, F.text)
    async def reg_full_name(message: Message, state: FSMContext) -> None:
        await state.update_data(full_name=message.text.strip())
        await message.answer(
            "Endi telefon raqamingizni yuboring:",
            reply_markup=request_phone_kb(),
        )
        await state.set_state(Registration.waiting_phone)

    @dp.message(Registration.waiting_phone, F.contact)
    async def reg_phone_contact(message: Message, state: FSMContext) -> None:
        contact: Contact = message.contact
        if contact.user_id and contact.user_id != message.from_user.id:
            await message.answer("Iltimos, o'z raqamingizni yuboring.")
            return
        await _finish_registration(message, state, contact.phone_number)

    @dp.message(Registration.waiting_phone, F.text)
    async def reg_phone_text(message: Message, state: FSMContext) -> None:
        await _finish_registration(message, state, message.text.strip())

    async def _finish_registration(message: Message, state: FSMContext, phone: str) -> None:
        data = await state.get_data()
        try:
            await user_service.register(
                RegistrationInput(
                    telegram_id=message.from_user.id,
                    full_name=data.get("full_name", ""),
                    phone_number=phone,
                )
            )
        except ValidationError as e:
            await message.answer(f"❗️ {e}\nQayta urinib ko'ring.")
            return
        await state.clear()
        # Bitta xabar: muvaffaqiyat + Mini App taklifi + inline tugma ostida.
        # Telegram cheklovi: bitta xabarda yo reply keyboard, yo inline keyboard.
        # Inline web_app tugmasini tanladik — `_main_kb` (Mahsulotlar/Savatcha/...)
        # keyingi /start yoki har bot bilan o'zaro aloqada sozlanadi (uzoq emas).
        if webapp_url:
            from aiogram.types import WebAppInfo
            await message.answer(
                f"✅ Ro'yxatdan muvaffaqiyatli o'tdingiz!\n"
                f"<b>{brand_name}</b> xizmatingizda 💧\n\n"
                f"💡 <b>Tezkor va qulay buyurtma</b>\n"
                f"Bir necha bosishda — quyidagi tugma orqali ilovaga kiring.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="🚀 Buyurtma berish",
                        web_app=WebAppInfo(url=webapp_url),
                    ),
                ]]),
            )
        else:
            # WebApp sozlanmagan — oddiy welcome + reply keyboard.
            await message.answer(
                f"✅ Ro'yxatdan muvaffaqiyatli o'tdingiz!\n"
                f"<b>{brand_name}</b> xizmatingizda 💧",
                reply_markup=_main_kb(),
            )

    # ---------------------- Asosiy menyu tugmalari ----------------------

    @dp.message(F.text == BTN_PRODUCTS)
    @dp.message(Command("products"))
    async def on_products(message: Message, state: FSMContext) -> None:
        await _show_products(message, state)

    @dp.message(F.text == BTN_CART)
    @dp.message(Command("cart"))
    async def on_cart(message: Message, state: FSMContext) -> None:
        await _render_cart(message, state)

    @dp.message(F.text == BTN_MY_ORDERS)
    @dp.message(Command("orders"))
    async def on_my_orders(message: Message) -> None:
        text, kb = await _build_orders_page(message.from_user.id, offset=0)
        await message.answer(text, reply_markup=kb)

    @dp.callback_query(F.data.startswith("myorders:page:"))
    async def on_orders_page(cb: CallbackQuery) -> None:
        try:
            offset = max(0, int(cb.data.split(":")[2]))
        except (ValueError, IndexError):
            await cb.answer()
            return
        text, kb = await _build_orders_page(cb.from_user.id, offset=offset)
        try:
            await cb.message.edit_text(text, reply_markup=kb)
        except TelegramAPIError:
            # message unchanged yoki tahrirlash mumkin emas — yangi xabar yuboramiz.
            await cb.message.answer(text, reply_markup=kb)
        await cb.answer()

    # ---------------------- Mahsulotlar menyusidagi tugmalar ----------------------

    @dp.message(Browsing.products, F.text == BTN_BACK)
    async def products_back(message: Message, state: FSMContext) -> None:
        await _go_main_menu(message, state)

    @dp.message(Browsing.products, F.text == BTN_CART)
    async def products_to_cart(message: Message, state: FSMContext) -> None:
        await _render_cart(message, state)

    @dp.message(Browsing.products, F.text)
    async def products_text(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()

        # Mahsulot nomi — kartani ochamiz va miqdor menyusiga o'tamiz.
        foods = await food_service.list_menu()
        food = next((f for f in foods if f.name == text), None)
        if food is None:
            await message.answer(
                "Iltimos, pastdagi menyudan mahsulotni tanlang."
            )
            return

        cart = _get_cart(await state.get_data())
        in_cart = cart.get(food.id, 0)
        await state.update_data(**{CURRENT_FOOD_KEY: food.id})
        await state.set_state(Browsing.in_product)
        await send_food_card(
            message,
            image_value=food.image_file_id,
            text=_food_card_text(food, in_cart),
            reply_markup=quantity_kb(int(getattr(food, "min_quantity", 1) or 1)),
        )

    # ---------------------- Mahsulot kartasi (miqdor tanlash) ----------------------

    @dp.message(Browsing.in_product, F.text == BTN_BACK)
    async def in_product_back(message: Message, state: FSMContext) -> None:
        await _show_products(message, state)

    @dp.message(Browsing.in_product, F.text)
    async def in_product_text(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer(
                "Iltimos, miqdorni tanlang yoki ⬅️ Orqaga bosing."
            )
            return

        data = await state.get_data()
        food_id = data.get(CURRENT_FOOD_KEY)
        if not food_id:
            await _show_products(message, state)
            return
        try:
            food = await food_service.get(int(food_id))
        except DomainError:
            await message.answer("Mahsulot topilmadi.")
            await _show_products(message, state)
            return

        qty = int(text)
        if qty > 999:
            await message.answer("❗️ Miqdor juda katta (999 dan oshmasin).")
            return
        cart = _get_cart(data)
        if qty == 0:
            cart.pop(food.id, None)
            await _save_cart(state, cart)
            await message.answer(f"<b>{food.name}</b> savatchadan olib tashlandi.")
            await _show_products(message, state)
            return
        # Per-mahsulot minimal buyurtma (0 = o'chirish — yuqorida hal qilingan).
        min_q = int(getattr(food, "min_quantity", 1) or 1)
        if qty < min_q:
            await message.answer(
                f"❗️ Minimal buyurtma: {min_q} dona. Kamida {min_q} dona kiriting."
            )
            return
        cart[food.id] = qty
        await _save_cart(state, cart)
        await message.answer(
            f"✅ <b>{food.name}</b> × {qty} savatchaga qo'shildi.\n\n"
            f"Buyurtma berish uchun pastdagi \"🛒 Savatcha\" tugmasini bosing."
        )
        await _show_products(message, state)

    # ---------------------- Savatcha menyusidagi tugmalar ----------------------

    @dp.message(Browsing.in_cart, F.text == BTN_BACK)
    async def cart_back(message: Message, state: FSMContext) -> None:
        await _show_products(message, state)

    @dp.message(Browsing.in_cart, F.text == BTN_CLEAR_CART)
    async def cart_clear(message: Message, state: FSMContext) -> None:
        await _save_cart(state, {})
        await message.answer("🗑 Savatcha tozalandi.")
        await _go_main_menu(message, state)

    @dp.message(Browsing.in_cart, F.text == BTN_CHECKOUT)
    async def cart_checkout(message: Message, state: FSMContext) -> None:
        cart = _get_cart(await state.get_data())
        if not cart:
            await message.answer("Savatcha bo'sh.", reply_markup=_main_kb())
            await state.set_state(None)
            return
        await message.answer(
            "📍 Yetkazib berish uchun <b>lokatsiyangizni</b> yuboring.\n\n"
            "Pastdagi tugma orqali joriy joyingizni jo'natishingiz yoki "
            "📎 (skrepka) → Location orqali xaritadan tanlashingiz mumkin.",
            reply_markup=request_location_kb(),
        )
        await state.set_state(Checkout.waiting_location)

    # ---------------------- Checkout ----------------------

    @dp.message(Checkout.waiting_location, F.location)
    async def checkout_location(message: Message, state: FSMContext) -> None:
        loc = message.location
        await state.update_data(latitude=loc.latitude, longitude=loc.longitude)
        user = await user_service.get_by_telegram_id(message.from_user.id)
        prompt = "📞 Aloqa uchun telefon raqamingizni kiriting"
        if user and user.phone_number:
            prompt += f" (ro'yxatda: {user.phone_number} — kerak bo'lsa boshqasini yozing)"
        await message.answer(prompt + ":", reply_markup=request_phone_kb())
        await state.set_state(Checkout.waiting_phone)

    @dp.message(Checkout.waiting_location)
    async def checkout_location_invalid(message: Message) -> None:
        await message.answer(
            "❗️ Iltimos, faqat <b>lokatsiya</b> yuboring (📍 tugmasi yoki 📎 → Location).",
            reply_markup=request_location_kb(),
        )

    @dp.message(Checkout.waiting_phone, F.contact)
    async def checkout_phone_contact(message: Message, state: FSMContext) -> None:
        await state.update_data(phone=message.contact.phone_number)
        await _ask_note(message, state)

    @dp.message(Checkout.waiting_phone, F.text)
    async def checkout_phone_text(message: Message, state: FSMContext) -> None:
        await state.update_data(phone=message.text.strip())
        await _ask_note(message, state)

    async def _ask_note(message: Message, state: FSMContext) -> None:
        await message.answer(
            "📝 Buyurtmaga izoh yozing (kuryer va oshpaz uchun maxsus ko'rsatma — masalan, "
            "podyezd, kvartira, qo'ng'iroq qilmaslik va h.k.):",
        )
        await state.set_state(Checkout.waiting_note)

    @dp.message(Checkout.waiting_note, F.text)
    async def checkout_note(message: Message, state: FSMContext) -> None:
        note = (message.text or "").strip()
        if not note:
            await message.answer(
                "❗️ Izoh bo'sh bo'lishi mumkin emas. Iltimos, qisqa izoh yozing:"
            )
            return
        if len(note) > 500:
            await message.answer("❗️ Izoh juda uzun (500 belgidan ko'p emas).")
            return
        await state.update_data(note=note)
        await _show_confirmation(message, state)

    @dp.message(Checkout.waiting_note)
    async def checkout_note_invalid(message: Message) -> None:
        await message.answer("❗️ Iltimos, izohni matn ko'rinishida yozing.")

    async def _show_confirmation(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        cart = _get_cart(data)
        lines = ["📋 <b>Buyurtmangizni tasdiqlang:</b>\n"]
        total = Decimal("0.00")
        for food_id, qty in cart.items():
            try:
                food = await food_service.get(food_id)
            except DomainError:
                continue
            line_total = food.price * qty
            total += line_total
            lines.append(f"• {food.name} × {qty} = {fmt_money(line_total)}")
        lines.append(f"\n<b>Jami:</b> {fmt_money(total)}")
        lat, lon = data.get("latitude"), data.get("longitude")
        if lat is not None and lon is not None:
            lines.append(
                f"📍 <a href='https://maps.google.com/?q={lat},{lon}'>lokatsiya</a>"
            )
        lines.append(f"📞 {data.get('phone')}")
        if data.get("note"):
            lines.append(f"📝 {data['note']}")
        lines.append("\n💵 To'lov: <b>naqd kuryerga</b>")
        await message.answer(
            "\n".join(lines),
            reply_markup=confirm_menu_kb(),
            disable_web_page_preview=True,
        )
        await state.set_state(Checkout.confirming)

    @dp.message(Checkout.confirming, F.text == BTN_CANCEL)
    async def checkout_cancel(message: Message, state: FSMContext) -> None:
        # FSM state'ni tozalaymiz, savatchani qoldiramiz — foydalanuvchi xohlasa qayta urinadi.
        await message.answer("❌ Buyurtma bekor qilindi.")
        await _go_main_menu(message, state)

    @dp.message(Checkout.confirming, F.text == BTN_CONFIRM)
    async def checkout_confirm(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        cart = _get_cart(data)
        items = [CartItem(food_id=fid, quantity=qty) for fid, qty in cart.items()]
        lat = data.get("latitude")
        lon = data.get("longitude")
        if lat is None or lon is None:
            await message.answer("❗️ Lokatsiya yo'q. Qayta urinib ko'ring.")
            await _go_main_menu(message, state)
            return

        # Idempotency: "Tasdiqlash" ikki marta tez bosilsa (yoki network retry)
        # ikkinchi chaqiruv MAVJUD orderni qaytaradi — duplikat yaratilmaydi.
        # Kalit state'da saqlanadi (bitta checkout sessiyasi = bitta kalit);
        # Mini App'dagi ensureOrderKey() bilan bir xil himoya.
        idem_key = data.get("idem_key")
        if not idem_key:
            import uuid as _uuid
            idem_key = _uuid.uuid4().hex
            await state.update_data(idem_key=idem_key)

        try:
            order = await order_service.create_order(
                NewOrderInput(
                    customer_telegram_id=message.from_user.id,
                    items=items,
                    delivery_latitude=float(lat),
                    delivery_longitude=float(lon),
                    contact_phone=data.get("phone", ""),
                    note=data.get("note", ""),
                    idempotency_key=idem_key,
                )
            )
        except DomainError as e:
            await message.answer(f"❗️ {e}")
            return

        await state.clear()

        # Mijoz DM da bitta "holat lentasi" xabari — keyinchalik kuryer transitsiyalari
        # shu xabarni edit qiladi (5 ta alohida xabar o'rniga 1 ta o'sib boruvchi).
        try:
            customer_msg_id = await notification_service.upsert_customer_status_message(order)
            if customer_msg_id is not None:
                await order_service.attach_customer_dm_message(order.id, customer_msg_id)
        except (TelegramAPIError, OSError) as e:
            log.warning("Mijoz status xabarini yuborib bo'lmadi #%s: %s", order.id, e)

        # Reply-keyboard'ni asosiy menyuga qaytarish uchun qisqa tasdiq.
        await message.answer(
            f"<b>{brand_name}</b> xizmatingizda !\nYana nimadir buyurtma qilasizmi ?",
            reply_markup=_main_kb(),
        )

        try:
            msg_id = await notification_service.dispatch_to_couriers_group(order)
            if msg_id is not None:
                await order_service.attach_group_message(order.id, msg_id)
        except (TelegramAPIError, OSError) as e:
            log.warning("Buyurtmani kuryer guruhiga yuborib bo'lmadi #%s: %s", order.id, e)
        # Har aktiv kuryerga DM (web app'ni ochuvchi tugma bilan) — best-effort.
        try:
            await notification_service.notify_couriers_new_order(order)
        except Exception as e:  # bildirishnoma buyurtmani buzmasin
            log.warning("Kuryerlarga DM bildirishnoma yuborilmadi #%s: %s", order.id, e)

    @dp.message(Checkout.confirming)
    async def checkout_confirming_other(message: Message) -> None:
        await message.answer(
            "Iltimos, pastdagi tugmalardan birini tanlang: "
            f"<b>{BTN_CONFIRM}</b> yoki <b>{BTN_CANCEL}</b>.",
            reply_markup=confirm_menu_kb(),
        )

    return dp


def make_customer_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
