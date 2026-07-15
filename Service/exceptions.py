"""Service qatlamining custom exception turlari.

Har bir exception **xato kodi** (translate'ga beriladi) va **context** lug'ati
bilan keladi. Bot/WebApp `Service/i18n.translate(err.code, **err.context)` orqali
foydalanuvchi tilidagi matnga aylantiradi.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from Service.i18n import translate


class DomainError(Exception):
    """Domain darajasidagi xatoliklar uchun bazaviy class.

    code — `Service/i18n.py` dagi kalit (masalan, "cart_empty").
    context — shablon parametrlari (masalan, max=999).
    """

    def __init__(
        self,
        code: str = "internal_error",
        *,
        context: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
    ) -> None:
        self.code = code
        self.context: Dict[str, Any] = dict(context or {})
        # message — ixtiyoriy override (eski kod yoki testlar uchun)
        self._message = message
        super().__init__(self.translate())

    def translate(self, locale: str = "uz") -> str:
        if self._message:
            return self._message
        return translate(self.code, locale=locale, **self.context)

    def __str__(self) -> str:
        return self.translate()


class ValidationError(DomainError):
    """Foydalanuvchi kiritgan ma'lumot noto'g'ri."""


class EntityNotFoundError(DomainError):
    """So'ralgan obyekt topilmadi."""


class InvalidOperationError(DomainError):
    """Hozirgi state'da ushbu operatsiyani bajarib bo'lmaydi."""
