"""OperatorService — call-operatorlar lifecycle'i (kuryer patterni).

Operator admin botga /start bosadi → noaktiv qator yaratiladi (adminlarga
DM xabar boradi) → admin Mini App "Operatorlar" bo'limidan aktivlashtiradi →
operator admin botning operator menyusi va "Yangi buyurtma" Mini App
sahifasidan foydalanadi. `operators` jadvali — YAGONA haqiqat manbai
(.env ro'yxati yo'q).
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from Data.unit_of_work import UnitOfWork
from Domain.models.operator import Operator
from Service.exceptions import EntityNotFoundError
from Service.phone import normalize_phone_or_none

log = logging.getLogger(__name__)


class OperatorService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_or_register(
        self,
        telegram_id: int,
        full_name: str,
        username: Optional[str] = None,
        *,
        mark_started: bool = True,
    ) -> tuple[Operator, bool]:
        """Admin bot /start: notanish user noaktiv operator sifatida ro'yxatga
        olinadi. Mavjudida ism/username sinxronlanadi. `is_active`ga bu yerda
        HECH QACHON tegilmaydi — faqat admin o'zgartiradi (kuryer patterni).

        Returns: (operator, created) — created=True YANGI ro'yxatga olinganda
        (caller adminlarga "yangi nomzod" xabarini yuboradi).
        """
        async with UnitOfWork(self._sf) as uow:
            op = await uow.operators.get_by_telegram_id(telegram_id)
            if op is None:
                op = Operator(
                    telegram_id=telegram_id,
                    full_name=full_name or f"Operator #{telegram_id}",
                    username=username,
                    is_active=False,
                    has_started_bot=mark_started,
                )
                await uow.operators.add(op)
                log.info("Yangi operator ro'yxatga olindi (tg=%s, noaktiv)", telegram_id)
                return op, True
            changed = False
            # Tarixan arxivlangan qator — tiklanadi (arxivlash tushunchasi
            # olib tashlangan; aks holda bunday operator /start bossa ham
            # ro'yxatda ko'rinmay, aktivlashtirib bo'lmay qolardi).
            if op.deleted_at is not None:
                op.deleted_at = None
                changed = True
            if full_name and op.full_name != full_name:
                op.full_name = full_name
                changed = True
            if username and op.username != username:
                op.username = username
                changed = True
            if mark_started and not op.has_started_bot:
                op.has_started_bot = True
                changed = True
            if changed:
                await uow.operators.add(op)
            return op, False

    async def is_active_operator(self, telegram_id: int) -> bool:
        """Admin bot filtri va webapp auth uchun — aktiv operatormi."""
        async with UnitOfWork(self._sf) as uow:
            return await uow.operators.is_active_operator(telegram_id)

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[Operator]:
        async with UnitOfWork(self._sf) as uow:
            return await uow.operators.get_by_telegram_id(telegram_id)

    async def get(self, operator_id: int) -> Operator:
        async with UnitOfWork(self._sf) as uow:
            op = await uow.operators.get(operator_id)
            if op is None:
                raise EntityNotFoundError("operator_not_found")
            return op

    async def list_paginated(
        self, *, limit: int = 50, offset: int = 0,
    ) -> tuple[Sequence[Operator], int]:
        async with UnitOfWork(self._sf) as uow:
            total = await uow.operators.count()
            items = await uow.operators.list_paginated(limit=limit, offset=offset)
            return items, total

    async def set_active(self, operator_id: int, active: bool) -> Operator:
        async with UnitOfWork(self._sf) as uow:
            op = await uow.operators.get(operator_id)
            if op is None:
                raise EntityNotFoundError("operator_not_found")
            op.is_active = active
            # Tarixiy arxiv belgisi qolgan bo'lsa tozalaymiz — aks holda
            # aktivlashtirilgan operator gate'dan o'tolmay qolardi.
            if op.deleted_at is not None:
                op.deleted_at = None
            await uow.operators.add(op)
            log.info("Operator %s %s qilindi", op.telegram_id, "aktiv" if active else "noaktiv")
            return op

    async def set_phone(self, operator_id: int, phone: Optional[str]) -> Operator:
        """Telefonni yangilash. Bo'sh → tozalash; aks holda +998 normalizatsiya."""
        normalized = normalize_phone_or_none(phone) if phone else None
        async with UnitOfWork(self._sf) as uow:
            op = await uow.operators.get(operator_id)
            if op is None:
                raise EntityNotFoundError("operator_not_found")
            op.phone_number = normalized
            # Tarixiy arxiv belgisi — har yozish yo'lida tozalanadi (izchillik).
            if op.deleted_at is not None:
                op.deleted_at = None
            await uow.operators.add(op)
            return op

    # Eslatma: operatorlarda ARXIVLASH YO'Q (egasi talabi) — ishdan ketgan
    # operator shunchaki NOAKTIV qilinadi. `deleted_at` ustuni jadvalda
    # tarixiy sabab bilan qoladi, lekin hech qayerda ishlatilmaydi.

