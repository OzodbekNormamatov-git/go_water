from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import func, select

from Data.repositories.base import BaseRepository
from Domain.models.promoter import Promoter, PromoterRedemption


class PromoterRepository(BaseRepository[Promoter]):
    """Promouterlar (uyma-uy ishchilar) jadvali.

    MUHIM — normalizatsiya: bu qatlam `promo_code` ni O'ZI normalizatsiya
    QILMAYDI. Chaqiruvchi (Service) `Service/promo_code.py:normalize_promo_code`
    orqali tayyorlab beradi. Sabab: `Data/` hech qachon `Service/` ni import
    qilmaydi (N-tier layering; `Service/phone.py` bilan bir xil yondashuv —
    UserService normalizatsiya qilib, repo'ga tayyor qiymat uzatadi).
    """

    model = Promoter

    async def get_by_code(self, promo_code: str) -> Optional[Promoter]:
        """Kod bo'yicha topish — NOAKTIV va ARXIVLANGANNI HAM qaytaradi.

        Yangi promouter yaratishda "bu kod band emasmi" tekshiruvi uchun:
        arxivlangan ishchining kodi ham QAYTA ISHLATILMASLIGI kerak, aks holda
        eski zakazlarning `promoter_code` snapshot'i yangi ishchiga tegishli
        bo'lib ko'rinib, tarix chalkashib ketardi.
        """
        res = await self._session.execute(
            select(Promoter).where(Promoter.promo_code == promo_code)
        )
        return res.scalar_one_or_none()

    async def get_redeemable_by_code(self, promo_code: str) -> Optional[Promoter]:
        """Mijoz kod kiritayotganda: FAQAT aktiv va arxivlanmagan promouter.

        Noaktiv/arxivlangan (ishdan ketgan) ishchining kodi endi o'tmaydi.
        Bu MAVJUD bog'lanishlarga ta'sir qilmaydi — faqat yangi kiritish yo'li.
        """
        res = await self._session.execute(
            select(Promoter).where(
                Promoter.promo_code == promo_code,
                Promoter.is_active.is_(True),
                Promoter.deleted_at.is_(None),
            )
        )
        return res.scalar_one_or_none()

    async def list_paginated(
        self, *, limit: int = 50, offset: int = 0, include_archived: bool = False,
    ) -> Sequence[Promoter]:
        """Paginatsiyalangan ro'yxat — avval aktivlar, keyin ism bo'yicha."""
        stmt = select(Promoter)
        if not include_archived:
            stmt = self._active_only(stmt)
        stmt = (
            stmt.order_by(Promoter.is_active.desc(), Promoter.full_name.asc())
            .offset(offset).limit(limit)
        )
        res = await self._session.execute(stmt)
        return res.scalars().all()

    async def count(self, *, include_archived: bool = False) -> int:
        stmt = select(func.count(Promoter.id))
        if not include_archived:
            stmt = self._active_only(stmt)
        res = await self._session.execute(stmt)
        return int(res.scalar_one() or 0)


class PromoterRedemptionRepository(BaseRepository[PromoterRedemption]):
    """Mijoz ↔ promouter bog'lanishlari (promokod ishlatilgan yozuvlar).

    `SoftDeleteMixin` YO'Q — bog'lanish append-only audit fakti: sodir bo'lgan
    voqeani "o'chirib" bo'lmaydi. Shuning uchun `_active_only` bu yerda ishlamaydi
    va kerak ham emas.
    """

    model = PromoterRedemption

    async def get_by_customer(self, customer_id: int) -> Optional[PromoterRedemption]:
        """Mijozning bog'lanishi (bo'lsa). `customer_id` UNIQUE — ko'pi bilan 1 ta."""
        res = await self._session.execute(
            select(PromoterRedemption).where(
                PromoterRedemption.customer_id == customer_id
            )
        )
        return res.scalar_one_or_none()

    async def counts_per_promoter(
        self, promoter_ids: Sequence[int],
    ) -> dict[int, int]:
        """N ta promouter uchun jalb qilingan mijozlar soni — bitta query.

        N+1 dan qochish (`stats_per_courier` patterni): har promouterga alohida
        count emas, yagona GROUP BY.
        """
        if not promoter_ids:
            return {}
        res = await self._session.execute(
            select(
                PromoterRedemption.promoter_id,
                func.count(PromoterRedemption.id),
            )
            .where(PromoterRedemption.promoter_id.in_(list(promoter_ids)))
            .group_by(PromoterRedemption.promoter_id)
        )
        return {int(r[0]): int(r[1] or 0) for r in res.all()}

    async def list_for_promoter(
        self, promoter_id: int, *, limit: int = 50, offset: int = 0,
    ) -> Sequence[PromoterRedemption]:
        """Bitta promouter jalb qilgan mijozlar — eng yangisi birinchi."""
        res = await self._session.execute(
            select(PromoterRedemption)
            .where(PromoterRedemption.promoter_id == promoter_id)
            .order_by(PromoterRedemption.created_at.desc())
            .offset(offset).limit(limit)
        )
        return res.scalars().all()

    async def count_for_promoter(self, promoter_id: int) -> int:
        res = await self._session.execute(
            select(func.count(PromoterRedemption.id)).where(
                PromoterRedemption.promoter_id == promoter_id
            )
        )
        return int(res.scalar_one() or 0)
