from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import exists, func, or_, select

from Data.repositories.base import BaseRepository
from Domain.models.user import User
from Domain.models.user_phone import UserPhone


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """Soft-deleted bo'lsa ham qaytaradi — restore va admin lookup uchun zarur."""
        res = await self._session.execute(select(User).where(User.telegram_id == telegram_id))
        return res.scalar_one_or_none()

    async def get_for_update(self, user_id: int) -> Optional[User]:
        """Pessimistic row-level lock — balans yangilash atomarligi uchun.
        Soft-deleted mijozning ham balansi yangilanishi mumkin (refund kabi).

        populate_existing MUHIM: instans shu sessiyada avvalroq (LOCKsiz,
        masalan Order.customer selectinload orqali) yuklangan bo'lsa, oddiy
        SELECT identity-map'dagi ESKI atributlarni yangilamaydi — balans
        lock olingunga QADAR boshqa tranzaksiya o'zgartirgan bo'lsa, hisob
        eski bazadan ketardi (lost update + ledger balance_after buzilishi).

        YOZISH-TO'SIG'I (write barrier): populate_existing DB'dan qayta
        o'qiydi — sessiyadagi hali FLUSH QILINMAGAN o'zgarishlar (masalan,
        order.status=DELIVERED; User.orders selectin zanjiri orqali qayta
        yuklanadi) aks holda ESKI qiymat bilan YO'Q QILINARDI (autoflush=False).
        Shuning uchun avval flush — o'z tranzaksiyamiz yozuvlari saqlanadi.
        """
        await self._session.flush()
        res = await self._session.execute(
            select(User).where(User.id == user_id).with_for_update()
            .execution_options(populate_existing=True)
        )
        return res.scalar_one_or_none()

    # ---------------------- Telefon raqamlar (user_phones) ----------------------

    async def get_by_any_phone(self, phone: str) -> Optional[User]:
        """Mijozni ISTALGAN (primary yoki qo'shimcha) raqami bo'yicha topadi.

        Haqiqat manbai `user_phones`; `users.phone_number` (primary kesh)
        fallback sifatida OR bilan qo'shiladi — backfill'gacha bo'lgan
        yozuvlar ham ishlashi uchun.
        """
        stmt = select(User).where(
            or_(
                User.phone_number == phone,
                User.id.in_(select(UserPhone.user_id).where(UserPhone.phone == phone)),
            )
        ).limit(1)
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_phone_row(self, phone_id: int) -> Optional[UserPhone]:
        return await self._session.get(UserPhone, phone_id)

    async def get_phone_row_by_number(self, phone: str) -> Optional[UserPhone]:
        res = await self._session.execute(
            select(UserPhone).where(UserPhone.phone == phone)
        )
        return res.scalar_one_or_none()

    async def list_phone_rows(self, user_id: int) -> Sequence[UserPhone]:
        res = await self._session.execute(
            select(UserPhone)
            .where(UserPhone.user_id == user_id)
            .order_by(UserPhone.is_primary.desc(), UserPhone.id.asc())
        )
        return res.scalars().all()

    async def count_phones(self, user_id: int) -> int:
        res = await self._session.execute(
            select(func.count(UserPhone.id)).where(UserPhone.user_id == user_id)
        )
        return int(res.scalar_one() or 0)

    @staticmethod
    def _apply_search_filter(stmt, query: str):
        q = (query or "").strip()
        if not q:
            return stmt
        like = f"%{q}%"
        return stmt.where(or_(
            User.full_name.ilike(like),
            User.phone_number.ilike(like),
            # Qo'shimcha raqamlar bo'yicha ham topilsin (user_phones EXISTS).
            exists(
                select(UserPhone.id).where(
                    UserPhone.user_id == User.id, UserPhone.phone.ilike(like),
                )
            ),
        ))

    async def search(
        self, query: str = "", *, limit: int = 50, offset: int = 0,
    ) -> Sequence[User]:
        """Admin "Mijozlar" ro'yxati — faqat aktivlar."""
        stmt = self._active_only(
            self._apply_search_filter(select(User), query).order_by(User.created_at.desc())
        )
        stmt = stmt.offset(offset).limit(limit)
        res = await self._session.execute(stmt)
        return res.scalars().all()

    async def search_name_or_phone(self, q: str, *, limit: int = 8) -> Sequence[User]:
        """Operator qidiruvi — ism YOKI telefon (qisman, oxirgi raqamlar ham).

        Telefon uchun q'dan faqat raqamlar ajratiladi (probel/`+`/`-` ahamiyatsiz),
        shuning uchun "90 12" yoki "1234" (oxirgi raqamlar) ham topadi. Trigram
        GIN indekslar tufayli katta bazada ham tez."""
        q = (q or "").strip()
        if len(q) < 2:
            return []
        conds = [User.full_name.ilike(f"%{q}%")]
        digits = re.sub(r"\D", "", q)
        if len(digits) >= 2:
            conds.append(User.phone_number.ilike(f"%{digits}%"))
            # Qo'shimcha raqamlar (user_phones) bo'yicha ham topilsin.
            conds.append(exists(
                select(UserPhone.id).where(
                    UserPhone.user_id == User.id,
                    UserPhone.phone.ilike(f"%{digits}%"),
                )
            ))
        stmt = self._active_only(
            select(User).where(or_(*conds)).order_by(User.created_at.desc()).limit(limit)
        )
        res = await self._session.execute(stmt)
        return res.scalars().all()

    async def count_search(self, query: str = "") -> int:
        stmt = self._active_only(
            self._apply_search_filter(select(func.count(User.id)), query)
        )
        res = await self._session.execute(stmt)
        return int(res.scalar_one() or 0)

    async def count_since(self, since: datetime) -> int:
        """Yangi (aktiv) mijozlar — arxivlangan dashboard'da hisoblanmaydi."""
        stmt = self._active_only(
            select(func.count(User.id)).where(User.created_at >= since)
        )
        res = await self._session.execute(stmt)
        return int(res.scalar_one() or 0)

    async def count_all(self) -> int:
        stmt = self._active_only(select(func.count(User.id)))
        res = await self._session.execute(stmt)
        return int(res.scalar_one() or 0)

    async def signups_by_day_since(self, since: datetime) -> list[tuple[str, int]]:
        dialect = self._session.bind.dialect.name if self._session.bind else "postgresql"
        if dialect == "postgresql":
            day_expr = func.date_trunc("day", User.created_at)
        else:
            day_expr = func.strftime("%Y-%m-%d", User.created_at)
        stmt = self._active_only(
            select(day_expr.label("day"), func.count(User.id).label("count"))
            .where(User.created_at >= since)
            .group_by("day")
            .order_by("day")
        )
        res = await self._session.execute(stmt)
        return [(str(r.day)[:10], int(r.count or 0)) for r in res.all()]

    async def list_active(self) -> Sequence[User]:
        """Barcha aktiv (arxivlanmagan) mijozlar — Aqlli eslatma hisoblashi uchun.

        Aqlli eslatma operator qo'ng'irog'i uchun, shuning uchun bot bilan ishlamagan
        (guest/opt-out) mijozlar HAM kiradi — telefon bor bo'lsa yetarli.
        """
        res = await self._session.execute(
            self._active_only(select(User).order_by(User.id.asc()))
        )
        return res.scalars().all()

    async def list_reminder_candidates(self) -> Sequence[User]:
        """Avto-eslatma nomzodlari: aktiv + botda faollashgan + opt-in + real ID.
        (Ochiq buyurtma / sikl / cooldown tekshiruvi service'da Python'da.)"""
        stmt = self._active_only(
            select(User).where(
                User.has_started_bot.is_(True),
                User.reminders_enabled.is_(True),
                User.telegram_id > 0,
            )
        )
        res = await self._session.execute(stmt)
        return res.scalars().all()

    async def list_all_telegram_ids(self) -> list[int]:
        """Broadcast uchun — faqat real, botda faollashgan aktiv mijozlar.

        Filtrlar:
          * `_active_only` — arxivlanganlar chiqarib tashlanadi
          * `telegram_id > 0` — operator yaratgan "guest" mijozlar sintetik
            manfiy ID ga ega; ularga DM yuborib bo'lmaydi (kafolatli failed)
          * `has_started_bot` — botga /start qilmaganlarga DM yuborib bo'lmaydi
        Shu tariqa broadcast.total/failed aniq bo'ladi va behuda API chaqiruv +
        rate-limit kechikishi sarflanmaydi."""
        res = await self._session.execute(
            self._active_only(
                select(User.telegram_id)
                .where(User.telegram_id > 0, User.has_started_bot.is_(True))
                .order_by(User.id.asc())
            )
        )
        return [int(r) for r in res.scalars().all()]

    async def cashback_liability_total(self) -> tuple[float, int]:
        """Faqat aktiv mijozlarning keshbek qarzlari — arxivlanganlar liability'dan chiqdi."""
        stmt = self._active_only(
            select(
                func.coalesce(func.sum(User.cashback_balance), 0),
                func.count(User.id),
            ).where(User.cashback_balance > 0)
        )
        res = await self._session.execute(stmt)
        row = res.first()
        return float(row[0] or 0), int(row[1] or 0)

    async def bottles_outstanding_total(self) -> tuple[int, int]:
        stmt = self._active_only(
            select(
                func.coalesce(func.sum(User.bottles_balance), 0),
                func.count(User.id),
            ).where(User.bottles_balance > 0)
        )
        res = await self._session.execute(stmt)
        row = res.first()
        return int(row[0] or 0), int(row[1] or 0)
