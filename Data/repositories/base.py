from __future__ import annotations

from datetime import datetime, timezone
from typing import Generic, Iterable, Optional, Sequence, Type, TypeVar

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from Domain.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BaseRepository(Generic[ModelT]):
    """Asos repository — generic CRUD + soft delete helperlari.

    Soft delete: model `SoftDeleteMixin` ga ega bo'lsa, `_active_only(stmt)`
    har bir listing query'siga `WHERE deleted_at IS NULL` qo'shadi. Standart
    `get()` arxivlangan obyektni HAM qaytaradi (tarix/restore uchun zarur).
    """

    model: Type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    # ---------------------- Soft delete helpers ----------------------

    @property
    def _deleted_at_col(self):
        """Model'da `deleted_at` ustuni mavjud bo'lsa, qaytaradi. Aks holda None."""
        return getattr(self.model, "deleted_at", None)

    def _active_only(self, stmt):
        """`WHERE deleted_at IS NULL` filtri qo'shadi (mixin bor bo'lsa)."""
        col = self._deleted_at_col
        if col is not None:
            stmt = stmt.where(col.is_(None))
        return stmt

    def _deleted_only(self, stmt):
        """Faqat arxivlangan qatorlar — admin "Arxiv" tab uchun."""
        col = self._deleted_at_col
        if col is not None:
            stmt = stmt.where(col.is_not(None))
        return stmt

    async def soft_delete(self, entity: ModelT) -> ModelT:
        """deleted_at = NOW(). Qator DB'da qoladi, listing'larda yashiriladi."""
        if self._deleted_at_col is None:
            raise RuntimeError(f"{self.model.__name__} soft delete'ga moslashtirilmagan")
        if getattr(entity, "deleted_at", None) is None:
            entity.deleted_at = _utcnow()  # type: ignore[attr-defined]
            self._session.add(entity)
            await self._session.flush()
        return entity

    async def restore(self, entity: ModelT) -> ModelT:
        """Arxivlangan qatorni qaytaradi (deleted_at = NULL)."""
        if self._deleted_at_col is None:
            raise RuntimeError(f"{self.model.__name__} soft delete'ga moslashtirilmagan")
        if getattr(entity, "deleted_at", None) is not None:
            entity.deleted_at = None  # type: ignore[attr-defined]
            self._session.add(entity)
            await self._session.flush()
        return entity

    # ---------------------- Standart CRUD ----------------------

    async def get(self, pk: int) -> Optional[ModelT]:
        """Soft-deleted bo'lsa ham qaytaradi — tarix/restore uchun zarur."""
        return await self._session.get(self.model, pk)

    async def list_all(self) -> Sequence[ModelT]:
        res = await self._session.execute(self._active_only(select(self.model)))
        return res.scalars().all()

    async def add(self, entity: ModelT) -> ModelT:
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def add_many(self, entities: Iterable[ModelT]) -> None:
        self._session.add_all(list(entities))
        await self._session.flush()

    async def delete(self, entity: ModelT) -> None:
        """HARD DELETE — qator butunlay yo'qoladi. Soft-delete modellari uchun
        `soft_delete()` ni ishlating; bu metod faqat ma'lumot tozalash uchun.
        """
        await self._session.delete(entity)
        await self._session.flush()

    async def delete_by_id(self, pk: int) -> int:
        res = await self._session.execute(delete(self.model).where(self.model.id == pk))
        await self._session.flush()
        return res.rowcount or 0
