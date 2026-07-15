from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Registration(StatesGroup):
    waiting_full_name = State()
    waiting_phone = State()


class Browsing(StatesGroup):
    """Reply-keyboard navigatsiyasi.

    - products: pastda mahsulotlar menyusi turibdi; mahsulot tanlanadi.
    - in_product: mahsulot kartasi ochilgan, pastda 3..11 miqdor tugmalari.
    - in_cart: pastda savatcha menyusi turibdi (rasmiylashtirish/tozalash/orqaga).
    """

    products = State()
    in_product = State()
    in_cart = State()


class Checkout(StatesGroup):
    waiting_location = State()
    waiting_phone = State()
    waiting_note = State()
    confirming = State()
