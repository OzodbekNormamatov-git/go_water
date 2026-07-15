"""BroadcastService — barcha mijozlarga ommaviy xabarnoma (Rassilka).

Service Telegram tomonidan amalga oshiriladi:
  * `customer_bot` orqali har bir mijozga DM yuboriladi
  * Yuborish foreground asyncio task'da — yangi yuborilgan har xabardan keyin
    DB'da `sent`/`failed` count yangilanadi (admin UI ko'rsatish uchun)
  * Telegram rate-limit (30 msg/sec/bot) — `BROADCAST_SEND_DELAY_SECONDS`
    bilan boshqariladi

Rasm + matn: agar `photo_path` mavjud bo'lsa, `send_photo(caption=body)`
orqali bitta xabar yuboriladi. Caption chegarasi (Telegram): 1024 belgi.

Concurrent ravishda bitta SENDING bo'lgan rassilkadan ortig'ini ishga
tushirmaymiz — admin oldingisini kutmasdan, ketma-ket yangisini boshlasa,
ikkinchisi xato (broadcast_already_running) bilan rad etiladi.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from Data.unit_of_work import UnitOfWork
from Domain.constants import (
    BROADCAST_SEND_DELAY_SECONDS,
    MAX_BROADCAST_BODY_LENGTH,
    MAX_BROADCAST_TITLE_LENGTH,
)
from Domain.models.broadcast import Broadcast, BroadcastStatus
from Service.exceptions import (
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)

# Telegram caption uchun belgi chegarasi
MAX_PHOTO_CAPTION_LENGTH = 1024
# Media katalog ildizi (rasm fayllarining nisbiy yo'liga tushadi).
_MEDIA_ROOT = Path(__file__).resolve().parent.parent

log = logging.getLogger(__name__)


@dataclass(slots=True)
class BroadcastInput:
    title: str
    body: str
    created_by: int
    photo_path: Optional[str] = None  # nisbiy yo'l (media/broadcasts/xxx.jpg)


def _validate(data: BroadcastInput) -> tuple[str, str]:
    title = (data.title or "").strip()
    body = (data.body or "").strip()
    if not body:
        raise ValidationError("broadcast_body_required")
    # Rasm bilan: caption chegarasi 1024 belgi (Telegram cheklovi).
    if data.photo_path and len(body) > MAX_PHOTO_CAPTION_LENGTH:
        raise ValidationError(
            "broadcast_caption_too_long", context={"max": MAX_PHOTO_CAPTION_LENGTH},
        )
    if len(body) > MAX_BROADCAST_BODY_LENGTH:
        raise ValidationError(
            "broadcast_body_too_long", context={"max": MAX_BROADCAST_BODY_LENGTH},
        )
    if len(title) > MAX_BROADCAST_TITLE_LENGTH:
        raise ValidationError(
            "broadcast_title_too_long", context={"max": MAX_BROADCAST_TITLE_LENGTH},
        )
    return title, body


class BroadcastService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        customer_bot: Bot,
    ) -> None:
        self._sf = session_factory
        self._bot = customer_bot
        # Hozir ishlayotgan rassilkalar — id -> task; cleanup uchun kerak.
        self._tasks: dict[int, asyncio.Task] = {}

    # ---------------------- CRUD / list ----------------------

    async def list_recent(self, limit: int = 30) -> List[Broadcast]:
        async with UnitOfWork(self._sf) as uow:
            return list(await uow.broadcasts.list_recent(limit=limit))

    async def list_paginated(
        self, *, limit: int = 30, offset: int = 0,
    ) -> tuple[List[Broadcast], int]:
        """Admin uchun: paginatsiyalangan rassilkalar + jami soni."""
        async with UnitOfWork(self._sf) as uow:
            total = await uow.broadcasts.count()
            items = list(await uow.broadcasts.list_paginated(limit=limit, offset=offset))
            return items, total

    async def get(self, broadcast_id: int) -> Broadcast:
        async with UnitOfWork(self._sf) as uow:
            br = await uow.broadcasts.get(broadcast_id)
            if br is None:
                raise EntityNotFoundError("broadcast_not_found")
            return br

    # ---------------------- Send ----------------------

    async def create_and_send(self, data: BroadcastInput) -> Broadcast:
        """Yangi rassilka yaratadi va background task'da yuborishni boshlaydi.

        Returns: yaratilgan `Broadcast` (status=SENDING). Yuborish jarayonini
        admin UI polling orqali kuzatadi (sent/failed/total).
        """
        title, body = _validate(data)
        photo_path = data.photo_path or None
        async with UnitOfWork(self._sf) as uow:
            active = await uow.broadcasts.get_active()
            if active is not None:
                raise InvalidOperationError("broadcast_already_running")
            # Mijozlar ro'yxati — yuborish kontekstida o'qiymiz (DB'ga muhrlangan total)
            tg_ids = await uow.users.list_all_telegram_ids()
            br = Broadcast(
                created_by=int(data.created_by),
                title=title,
                body=body,
                photo_path=photo_path,
                status=BroadcastStatus.SENDING,
                total=len(tg_ids),
                sent=0,
                failed=0,
                started_at=datetime.now(timezone.utc),
            )
            br = await uow.broadcasts.add(br)
            broadcast_id = br.id
            broadcast_body = br.body
            broadcast_photo = br.photo_path

        # Yuborishni background'da boshlaymiz. Asosiy javobni bloklamaymiz.
        task = asyncio.create_task(
            self._run(broadcast_id, broadcast_body, tg_ids, photo_path=broadcast_photo),
            name=f"broadcast-{broadcast_id}",
        )
        self._tasks[broadcast_id] = task

        async with UnitOfWork(self._sf) as uow:
            return await uow.broadcasts.get(broadcast_id)  # type: ignore[return-value]

    async def cancel(self, broadcast_id: int) -> Broadcast:
        async with UnitOfWork(self._sf) as uow:
            br = await uow.broadcasts.get(broadcast_id)
            if br is None:
                raise EntityNotFoundError("broadcast_not_found")
            if br.status.is_terminal:
                return br
            br.status = BroadcastStatus.CANCELLED
            br.finished_at = datetime.now(timezone.utc)
            await uow.broadcasts.add(br)
        task = self._tasks.pop(broadcast_id, None)
        if task and not task.done():
            task.cancel()
        return br

    # ---------------------- Internal background task ----------------------

    async def _run(
        self,
        broadcast_id: int,
        body: str,
        tg_ids: List[int],
        *,
        photo_path: Optional[str] = None,
    ) -> None:
        """Asl yuboruvchi — har bir mijozga DM yuboradi va sent/failed yangilab boradi.

        Rasm bilan: `send_photo(caption=body)` — bitta xabar (Telegram caption max 1024).
        Rasmsiz: `send_message(text=body)` — uzun matn (3500 belgigacha).
        """
        sent = 0
        failed = 0
        last_err = ""
        CHECKPOINT_EVERY = 20

        # Rasm bo'lsa, mutlaq yo'lni topib, mavjudligini tekshiramiz (yo'qolgan
        # bo'lsa — matn-only fallback).
        photo_abs: Optional[Path] = None
        if photo_path:
            candidate = _MEDIA_ROOT / photo_path
            if candidate.is_file():
                photo_abs = candidate
            else:
                log.warning("Broadcast %s: photo not found at %s — falling back to text-only",
                            broadcast_id, candidate)

        try:
            for idx, tg_id in enumerate(tg_ids, start=1):
                if (idx % 50) == 0:
                    if await self._is_cancelled(broadcast_id):
                        break

                try:
                    if photo_abs is not None:
                        await self._bot.send_photo(
                            chat_id=int(tg_id),
                            photo=FSInputFile(str(photo_abs)),
                            caption=body,
                        )
                    else:
                        await self._bot.send_message(
                            chat_id=int(tg_id),
                            text=body,
                            disable_web_page_preview=True,
                        )
                    sent += 1
                except TelegramAPIError as e:
                    failed += 1
                    last_err = str(e)[:200]
                    log.debug("Broadcast %s: tg=%s failed: %s", broadcast_id, tg_id, e)

                await asyncio.sleep(BROADCAST_SEND_DELAY_SECONDS)

                if (idx % CHECKPOINT_EVERY) == 0:
                    await self._checkpoint(broadcast_id, sent=sent, failed=failed, last_error=last_err)

            await self._finalize(broadcast_id, sent=sent, failed=failed, last_error=last_err, status=BroadcastStatus.DONE)
        except asyncio.CancelledError:
            await self._checkpoint(broadcast_id, sent=sent, failed=failed, last_error="cancelled")
            raise
        except Exception as e:
            log.exception("Broadcast %s crashed", broadcast_id)
            await self._finalize(
                broadcast_id, sent=sent, failed=failed, last_error=str(e)[:200], status=BroadcastStatus.FAILED,
            )
        finally:
            self._tasks.pop(broadcast_id, None)

    async def _is_cancelled(self, broadcast_id: int) -> bool:
        async with UnitOfWork(self._sf) as uow:
            br = await uow.broadcasts.get(broadcast_id)
            return br is not None and br.status == BroadcastStatus.CANCELLED

    async def _checkpoint(
        self, broadcast_id: int, *, sent: int, failed: int, last_error: str,
    ) -> None:
        async with UnitOfWork(self._sf) as uow:
            br = await uow.broadcasts.get(broadcast_id)
            if br is None:
                return
            br.sent = sent
            br.failed = failed
            if last_error:
                br.last_error = last_error
            await uow.broadcasts.add(br)

    async def _finalize(
        self,
        broadcast_id: int,
        *,
        sent: int,
        failed: int,
        last_error: str,
        status: BroadcastStatus,
    ) -> None:
        async with UnitOfWork(self._sf) as uow:
            br = await uow.broadcasts.get(broadcast_id)
            if br is None:
                return
            br.sent = sent
            br.failed = failed
            br.last_error = last_error
            if br.status != BroadcastStatus.CANCELLED:
                # Cancel oldindan kelgan bo'lsa — uni saqlab qolamiz
                br.status = status
            br.finished_at = datetime.now(timezone.utc)
            await uow.broadcasts.add(br)
