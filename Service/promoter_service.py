"""PromoterService — uyma-uy ishchilar, promokodlar, atributsiya va KPI.

Biznes oqimi:
  1. Admin promouter yaratadi → unga NOYOB, O'ZGARMAS kod tegadi.
  2. Promouter mijoznikiga boradi: botni tushuntiradi, manzil saqlashga o'rgatadi.
  3. Mijozning telefonida, uning ruxsati bilan, o'z kodini kiritadi.
  4. Shartlar: mijozda 0 ta zakaz VA >= 1 saqlangan manzil.
  5. Keyingi zakazlar promouterga yoziladi → KPI/bonus.

ATRIBUTSIYA va BONUS ATAYLAB AJRATILGAN (`resolve_order_attribution` ga qarang):
  * `promoter_id` — "bu mijozni kim olib kelgan" — ABADIY fakt, doim yoziladi.
  * `promoter_bonus_amount` — pul — faqat shartlar bajarilsa > 0.
Shu sababli promouter ishdan ketsa yoki bonus davri tugasa, `orders` jadvalida
HECH QANDAY muammo yuzaga kelmaydi: atributsiya joyida qoladi, bonus 0 bo'ladi.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from Data.unit_of_work import UnitOfWork
from Domain.constants import (
    DEFAULT_PROMOTER_BONUS_WINDOW_DAYS,
    PROMO_CODE_GENERATED_LENGTH,
)
from Domain.models.promoter import Promoter, PromoterRedemption
from Service.exceptions import (
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from Service.phone import normalize_phone_or_none
from Service.promo_code import (
    generate_promo_code,
    normalize_promo_code,
    normalize_promo_code_lenient,
)

# Avtomatik kod yaratishda noyob qiymat topish uchun urinishlar soni.
# Har urinish DB'ga bitta so'rov; 31 belgili alifboda 6 uzunlik = ~887 mln
# variant, shuning uchun 10 urinish amalda hech qachon tugamaydi.
_CODE_GENERATION_ATTEMPTS = 10

MIN_NAME_LENGTH = 2


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class PromoterStats:
    """Bitta promouterning KPI ko'rinishi (admin paneli uchun sof DTO)."""
    id: int
    full_name: str
    phone_number: Optional[str]
    promo_code: str
    is_active: bool
    is_archived: bool
    created_at: datetime
    # Jalb qilingan mijozlar soni (promokod kiritganlar).
    customers: int
    # KPI: shu promouterga yozilgan YETKAZILGAN zakazlar soni.
    delivered_orders: int
    # KPI: jami to'lanadigan bonus (muhrlangan summalar yig'indisi).
    bonus_total: Decimal


@dataclass(slots=True)
class PromoterEligibility:
    """Mijoz promokod kiritishga haqlimi — Mini App UI'ni gate qilish uchun.

    Frontend shu obyektga qarab "Promokod" bo'limini ko'rsatadi yoki yashiradi.
    Yakuniy qaror HAR DOIM serverda (`redeem`) — bu faqat UI uchun maslahat.
    """
    program_enabled: bool
    already_redeemed: bool
    redeemed_code: str
    has_orders: bool
    has_address: bool
    eligible: bool
    # Frontend'ga aynan nimani ko'rsatishni aytadigan sabab kodi (i18n kaliti).
    # `eligible=True` bo'lsa "".
    reason: str


async def resolve_order_attribution(
    uow: UnitOfWork, customer_id: int, *, now: Optional[datetime] = None,
) -> Tuple[Optional[int], str, Decimal]:
    """Yangi zakaz uchun (promoter_id, promo_code, bonus) ni aniqlaydi.

    `OrderService.create_order` ichidan, O'SHA UoW/tranzaksiya doirasida
    chaqiriladi (yangi sessiya ochmaydi — atomiklik buzilmasin).

    Qaytaradi — uchtasi ham `orders` qatoriga MUHRLANADI:
      * promoter_id — bog'lanish bor bo'lsa DOIM (davr tugagan yoki promouter
        ishdan ketgan bo'lsa ham). Bu "kim olib kelgan" tahlilini saqlaydi.
      * promo_code  — snapshot (promouter qatori yo'qolsa ham audit qoladi).
      * bonus       — FAQAT quyidagilarning HAMMASI bajarilsa > 0:
            dastur yoqilgan  +  davr tugamagan  +  promouter aktiv va arxivlanmagan
        Aks holda 0.00 — zakaz baribir yoziladi, shunchaki puli yo'q.
    """
    red = await uow.promoter_redemptions.get_by_customer(customer_id)
    if red is None:
        return None, "", Decimal("0.00")

    # --- Atributsiya: shartsiz, abadiy fakt ---
    promoter_id: Optional[int] = red.promoter_id
    code: str = red.promo_code or ""
    zero = Decimal("0.00")

    # --- Bonus: shartli ---
    cfg = await uow.settings.get_or_create()
    if not bool(cfg.promoter_program_enabled):
        return promoter_id, code, zero

    moment = now or _utcnow()
    window_end = red.bonus_window_ends_at
    # DB'dan naive datetime kelib qolsa (eski qator / sozlama), UTC deb qaraymiz
    # — aks holda offset-naive va offset-aware taqqoslash TypeError beradi.
    if window_end is not None and window_end.tzinfo is None:
        window_end = window_end.replace(tzinfo=timezone.utc)
    if window_end is not None and moment > window_end:
        return promoter_id, code, zero

    promoter = await uow.promoters.get(promoter_id)
    if promoter is None or not promoter.is_active or promoter.deleted_at is not None:
        # Ishdan ketgan / to'xtatilgan ishchi: atributsiya qoladi, bonus yo'q.
        return promoter_id, code, zero

    bonus = Decimal(str(cfg.promoter_bonus_per_order or 0))
    if bonus <= 0:
        return promoter_id, code, zero
    return promoter_id, code, bonus.quantize(Decimal("0.01"))


class PromoterService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ==================== Mijoz tomoni ====================

    async def eligibility(self, customer_telegram_id: int) -> PromoterEligibility:
        """Mijoz promokod kiritishga haqlimi (Mini App UI gate'i uchun)."""
        async with UnitOfWork(self._sf) as uow:
            cfg = await uow.settings.get_or_create()
            enabled = bool(cfg.promoter_program_enabled)

            user = await uow.users.get_by_telegram_id(customer_telegram_id)
            if user is None:
                raise InvalidOperationError("user_not_registered")

            red = await uow.promoter_redemptions.get_by_customer(user.id)
            has_orders = await uow.orders.has_any_order(user.id)
            has_address = (await uow.addresses.count_for_customer(user.id)) > 0

            if not enabled:
                reason = "promoter_program_disabled"
            elif red is not None:
                reason = "promo_code_already_used"
            elif has_orders:
                reason = "promo_code_customer_has_orders"
            elif not has_address:
                reason = "promo_code_no_address"
            else:
                reason = ""

            return PromoterEligibility(
                program_enabled=enabled,
                already_redeemed=red is not None,
                redeemed_code=(red.promo_code if red is not None else ""),
                has_orders=has_orders,
                has_address=has_address,
                eligible=(reason == ""),
                reason=reason,
            )

    async def redeem(
        self, customer_telegram_id: int, raw_code: str,
    ) -> PromoterRedemption:
        """Mijoz hisobida promokodni faollashtiradi.

        Shartlar (server tomonda, HAR DOIM qayta tekshiriladi — frontend
        gate'iga ishonilmaydi):
          1. Dastur yoqilgan bo'lishi
          2. Kod mavjud, promouter AKTIV va arxivlanmagan
          3. Mijoz avval kod kiritmagan bo'lishi
          4. Mijozda 0 ta zakaz (QAT'IY: bekor/arxiv ham sanaladi)
          5. Mijozda >= 1 saqlangan manzil

        RACE XAVFSIZLIGI — ikki qavat:
          a) Mijoz qatori `get_for_update` bilan LOCK qilinadi. `create_order`
             ham AYNAN shu qatorni lock qiladi, shuning uchun "kod kiritish" va
             "birinchi zakaz" bir vaqtda kecholmaydi — biri ikkinchisini kutadi,
             va kutgani yangilangan holatni ko'radi (4-shart buzilmaydi).
          b) Bir vaqtda ikkita kod kiritilsa — `promoter_redemptions.customer_id`
             UNIQUE constraint'i ikkinchisini IntegrityError bilan rad etadi.
        """
        code = normalize_promo_code_lenient(raw_code)
        if not code:
            # Format xatosi ham, "topilmadi" ham — mijozga bitta xabar.
            raise ValidationError("promo_code_invalid")

        async with UnitOfWork(self._sf) as uow:
            cfg = await uow.settings.get_or_create()
            if not bool(cfg.promoter_program_enabled):
                raise InvalidOperationError("promoter_program_disabled")

            user_row = await uow.users.get_by_telegram_id(customer_telegram_id)
            if user_row is None:
                raise InvalidOperationError("user_not_registered")
            # LOCK — `create_order` bilan bir xil qator (race yopiladi).
            user = await uow.users.get_for_update(user_row.id) or user_row

            promoter = await uow.promoters.get_redeemable_by_code(code)
            if promoter is None:
                raise ValidationError("promo_code_invalid")

            if await uow.promoter_redemptions.get_by_customer(user.id) is not None:
                raise InvalidOperationError("promo_code_already_used")

            if await uow.orders.has_any_order(user.id):
                raise InvalidOperationError("promo_code_customer_has_orders")

            if (await uow.addresses.count_for_customer(user.id)) <= 0:
                raise InvalidOperationError("promo_code_no_address")

            window_days = int(
                cfg.promoter_bonus_window_days or DEFAULT_PROMOTER_BONUS_WINDOW_DAYS
            )
            red = PromoterRedemption(
                customer_id=user.id,
                promoter_id=promoter.id,
                # Kodni promouter qatoridan olamiz (kiritilgandan emas) —
                # kanonik qiymat kafolatlanadi.
                promo_code=promoter.promo_code,
                # Davr MUHRLANADI: admin keyin sozlamani o'zgartirsa, allaqachon
                # bog'langan mijozlarning sharti retroaktiv o'zgarmaydi.
                bonus_window_ends_at=_utcnow() + timedelta(days=window_days),
            )
            try:
                await uow.promoter_redemptions.add(red)
            except IntegrityError:
                # UNIQUE(customer_id) — parallel ikkinchi so'rov.
                raise InvalidOperationError("promo_code_already_used")
            return red

    # ==================== Admin tomoni ====================

    async def create(
        self, *, full_name: str, phone_number: Optional[str] = None,
        promo_code: Optional[str] = None,
    ) -> Promoter:
        """Yangi promouter yaratadi. Kod berilmasa — avtomatik generatsiya.

        Kod band bo'lsa `promoter_code_taken` — arxivlangan promouterning kodi
        ham band hisoblanadi (`get_by_code` arxivni ham ko'radi): eski
        zakazlarning `promoter_code` snapshot'i yangi ishchiga tegishli bo'lib
        ko'rinmasligi kerak.
        """
        name = (full_name or "").strip()
        if len(name) < MIN_NAME_LENGTH:
            raise ValidationError("name_too_short")
        phone = normalize_phone_or_none(phone_number)

        async with UnitOfWork(self._sf) as uow:
            if promo_code:
                code = normalize_promo_code(promo_code)
                if await uow.promoters.get_by_code(code) is not None:
                    raise ValidationError("promoter_code_taken", context={"code": code})
            else:
                code = ""
                for _ in range(_CODE_GENERATION_ATTEMPTS):
                    candidate = generate_promo_code(PROMO_CODE_GENERATED_LENGTH)
                    if await uow.promoters.get_by_code(candidate) is None:
                        code = candidate
                        break
                if not code:
                    raise InvalidOperationError("promoter_code_generation_failed")

            promoter = Promoter(
                full_name=name, phone_number=phone, promo_code=code, is_active=True,
            )
            try:
                await uow.promoters.add(promoter)
            except IntegrityError:
                # UNIQUE(promo_code) — parallel yaratish.
                raise ValidationError("promoter_code_taken", context={"code": code})
            return promoter

    async def update(
        self, promoter_id: int, *, full_name: Optional[str] = None,
        phone_number: Optional[str] = None, is_active: Optional[bool] = None,
    ) -> Promoter:
        """Promouterni yangilaydi (PATCH semantikasi).

        `promo_code` ATAYLAB YO'Q — kod o'zgarmas. U zakaz qatorlariga snapshot
        bo'lib muhrlangan va bosma materiallarda tarqalgan; o'zgartirilsa tarix
        bilan aloqa uzilardi. Kodni "almashtirish" kerak bo'lsa — eskisini
        noaktiv qilib, yangi promouter yaratiladi.
        """
        async with UnitOfWork(self._sf) as uow:
            promoter = await uow.promoters.get(promoter_id)
            if promoter is None:
                raise EntityNotFoundError("promoter_not_found")
            if full_name is not None:
                name = (full_name or "").strip()
                if len(name) < MIN_NAME_LENGTH:
                    raise ValidationError("name_too_short")
                promoter.full_name = name
            if phone_number is not None:
                promoter.phone_number = normalize_phone_or_none(phone_number)
            if is_active is not None:
                promoter.is_active = bool(is_active)
            await uow.promoters.add(promoter)
            return promoter

    async def archive(self, promoter_id: int) -> Promoter:
        """Ishdan ketgan promouterni arxivlaydi (soft delete).

        Qator DB'da QOLADI — `orders.promoter_id` va `promoter_redemptions`
        FK'lari buzilmaydi, tarixiy KPI ko'rinaveradi. Kod endi o'tmaydi va
        yangi zakazlarga bonus yozilmaydi.
        """
        async with UnitOfWork(self._sf) as uow:
            promoter = await uow.promoters.get(promoter_id)
            if promoter is None:
                raise EntityNotFoundError("promoter_not_found")
            await uow.promoters.soft_delete(promoter)
            return promoter

    async def restore(self, promoter_id: int) -> Promoter:
        async with UnitOfWork(self._sf) as uow:
            promoter = await uow.promoters.get(promoter_id)
            if promoter is None:
                raise EntityNotFoundError("promoter_not_found")
            await uow.promoters.restore(promoter)
            return promoter

    async def list_with_stats(
        self, *, limit: int = 50, offset: int = 0,
        include_archived: bool = False, since: Optional[datetime] = None,
    ) -> Tuple[List[PromoterStats], int]:
        """Promouterlar ro'yxati + KPI. Qaytaradi: (elementlar, jami son).

        N+1 YO'Q: barcha promouterlar uchun statistika ikkita GROUP BY so'rovda
        yig'iladi (`stats_per_promoter`, `counts_per_promoter`).
        """
        async with UnitOfWork(self._sf) as uow:
            rows = await uow.promoters.list_paginated(
                limit=limit, offset=offset, include_archived=include_archived,
            )
            total = await uow.promoters.count(include_archived=include_archived)
            ids = [p.id for p in rows]
            order_stats = await uow.orders.stats_per_promoter(ids, since=since)
            cust_counts = await uow.promoter_redemptions.counts_per_promoter(ids)
            return [_to_stats(p, order_stats, cust_counts) for p in rows], total

    async def get_with_stats(
        self, promoter_id: int, *, since: Optional[datetime] = None,
    ) -> PromoterStats:
        async with UnitOfWork(self._sf) as uow:
            promoter = await uow.promoters.get(promoter_id)
            if promoter is None:
                raise EntityNotFoundError("promoter_not_found")
            order_stats = await uow.orders.stats_per_promoter([promoter.id], since=since)
            cust_counts = await uow.promoter_redemptions.counts_per_promoter([promoter.id])
            return _to_stats(promoter, order_stats, cust_counts)

    async def list_customers(
        self, promoter_id: int, *, limit: int = 50, offset: int = 0,
    ) -> Tuple[Sequence[PromoterRedemption], int]:
        """Promouter jalb qilgan mijozlar (bog'lanish yozuvlari) + jami son."""
        async with UnitOfWork(self._sf) as uow:
            promoter = await uow.promoters.get(promoter_id)
            if promoter is None:
                raise EntityNotFoundError("promoter_not_found")
            rows = await uow.promoter_redemptions.list_for_promoter(
                promoter_id, limit=limit, offset=offset,
            )
            total = await uow.promoter_redemptions.count_for_promoter(promoter_id)
            return rows, total


def _to_stats(
    p: Promoter,
    order_stats: dict[int, Tuple[int, Decimal]],
    cust_counts: dict[int, int],
) -> PromoterStats:
    orders, bonus = order_stats.get(p.id, (0, Decimal("0.00")))
    return PromoterStats(
        id=p.id,
        full_name=p.full_name,
        phone_number=p.phone_number,
        promo_code=p.promo_code,
        is_active=bool(p.is_active),
        is_archived=p.deleted_at is not None,
        created_at=p.created_at,
        customers=cust_counts.get(p.id, 0),
        delivered_orders=orders,
        bonus_total=bonus,
    )
