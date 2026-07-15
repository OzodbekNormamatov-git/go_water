"""baseline schema — mavjud production bazasi uchun stamp boshlanish nuqtasi.

Mavjud baza ustida ushbu migratsiya birinchi marta:
    alembic stamp 0001_baseline
ko'rinishida belgilanadi (DDL ishlatilmasdan, faqat alembic versiya yozuvi
yaratiladi). Yangi bo'sh DB'da `alembic upgrade head` chaqirilsa, modellardan
`Base.metadata.create_all` qo'llanadi.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from Domain.models.base import Base

# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Bo'sh DB'da modellardagi metadata bo'yicha barcha jadvallarni yaratadi.

    Mavjud bazada bu migratsiya `alembic stamp 0001_baseline` orqali
    o'tkazib yuboriladi (jadvallar allaqachon mavjud).
    """
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Faqat dev/test uchun — barcha jadvallarni o'chiradi.

    Production'da hech qachon chaqirmang.
    """
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
