from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class SoftDeleteMixin:
    """Soft delete pattern — `deleted_at IS NULL` = aktiv; sana = arxivlangan.

    Standart xulq-atvor: barcha ro'yxat/stat metodlari `WHERE deleted_at IS NULL`
    filtri qo'llaydi (`BaseRepository._active_only()`). Tarix kerak bo'lganda
    (Order detail, snapshot ko'rinish) `get()` arxivlangan obyektni ham qaytaradi.

    Soft delete'ning ustunligi:
      * Tasodifiy o'chirish qaytariladigan (restore)
      * Mahsulot / mijoz / kuryer arxivlansa-da, eski buyurtmalarda asl ma'lumot ko'rinadi
      * Hisobotlarda "qachon o'chirilgan" audit ma'lumot saqlanadi
      * `purge()` (hard delete) faqat tozalash ishlari uchun
    """
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
