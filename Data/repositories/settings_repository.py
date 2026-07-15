"""SettingsRepository — singleton qator (id=1) bilan ishlash."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from Data.repositories.base import BaseRepository
from Domain.models.app_settings import AppSettings


SINGLETON_ID = 1


class SettingsRepository(BaseRepository[AppSettings]):
    model = AppSettings

    async def get_singleton(self) -> Optional[AppSettings]:
        return await self._session.get(AppSettings, SINGLETON_ID)

    async def get_for_update(self) -> AppSettings:
        """Row-lock — admin sozlamani yangilash uchun atomik."""
        res = await self._session.execute(
            select(AppSettings).where(AppSettings.id == SINGLETON_ID).with_for_update()
        )
        obj = res.scalar_one_or_none()
        if obj is None:
            obj = AppSettings(id=SINGLETON_ID)
            self._session.add(obj)
            await self._session.flush()
        return obj

    async def get_or_create(self) -> AppSettings:
        """Sozlamalarni o'qib qaytaradi; bo'sh bo'lsa default qator yaratadi."""
        obj = await self.get_singleton()
        if obj is None:
            obj = AppSettings(id=SINGLETON_ID)
            self._session.add(obj)
            await self._session.flush()
        return obj
