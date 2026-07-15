"""ReminderRepository — avto-eslatma jurnali (dedup, churn-cap, audit)."""
from __future__ import annotations

from datetime import datetime
from typing import Sequence, Tuple

from sqlalchemy import select

from Data.repositories.base import BaseRepository
from Domain.models.reminder import Reminder


class ReminderRepository(BaseRepository[Reminder]):
    model = Reminder

    async def all_sent_times(self) -> Sequence[Tuple[int, datetime]]:
        """Barcha (customer_id, sent_at) — kunlik job Python'da guruhlaydi.

        Hajm kichik (mijoz uchun oyiga bir nechta), shuning uchun bitta bulk
        so'rov yetarli (N+1 yo'q)."""
        res = await self._session.execute(
            select(Reminder.customer_id, Reminder.sent_at)
        )
        return [(int(c), t) for c, t in res.all()]
