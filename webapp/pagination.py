"""Pagination helper — bir xil response shakli ham mijoz, ham admin uchun.

Foydalanish (route'da):
    items = await ...
    total = await ...
    return Page[T](items=items, total=total, limit=limit, offset=offset)
"""
from __future__ import annotations

from typing import Generic, List, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Universal sahifalangan javob.

    `has_more` qisqartirilgan helper (frontend uchun) — `offset + len(items) < total`.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    items: List[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return (self.offset + len(self.items)) < self.total
