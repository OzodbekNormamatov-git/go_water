from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional, Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from Data.unit_of_work import UnitOfWork
from Domain.constants import MAX_PHONES_PER_USER
from Domain.models.ledger import LedgerAccount, LedgerKind
from Domain.models.user import User
from Domain.models.user_phone import UserPhone
from Service.ledger_posting import post_ledger
from Service.exceptions import (
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
# Telefon normalizatsiyasi — yagona manba (Service/phone.py, +998 avto).
# `normalize_phone_or_none` bu moduldan re-eksport (mavjud importlar buzilmasin).
from Service.phone import normalize_phone as _normalize_phone
from Service.phone import normalize_phone_or_none

log = logging.getLogger(__name__)


@dataclass(slots=True)
class RegistrationInput:
    telegram_id: int
    full_name: str
    phone_number: str


async def _sync_primary_phone(uow: UnitOfWork, user: User, phone: str) -> None:
    """`user_phones` jadvalini va `users.phone_number` keshini sinxron tutadi.

    Chaqiruvchi telefonning BOSHQA mijozga tegishli emasligini oldindan
    tekshirgan bo'lishi shart (register/find_or_create shunday qiladi).
      * Raqam shu mijozda bor — primary qilib belgilaydi.
      * Yo'q — yangi primary qator qo'shadi.
      * Eski primary (boshqa raqam) — oddiy (qo'shimcha) raqamga tushadi:
        mijoz raqam almashtirsa, eski raqami tarixda qoladi (identifikatsiya).
    """
    rows = await uow.users.list_phone_rows(user.id)
    target = next((r for r in rows if r.phone == phone), None)
    # 1-bosqich: eski primary'ni ALOHIDA flush bilan tushiramiz — partial
    # unique indeks (user_id WHERE is_primary) oraliq holatda buzilmasin
    # (bitta flush ichida UPDATE/INSERT tartibi kafolatlanmagan).
    demoted = False
    for r in rows:
        if r.is_primary and r is not target:
            r.is_primary = False
            uow.session.add(r)
            demoted = True
    if demoted:
        await uow.session.flush()
    # 2-bosqich: yangi primary.
    if target is None:
        target = UserPhone(user_id=user.id, phone=phone, is_primary=True)
        uow.session.add(target)
    elif not target.is_primary:
        target.is_primary = True
        uow.session.add(target)
    # Kesh — users.phone_number doim primary raqam bilan teng.
    if user.phone_number != phone:
        user.phone_number = phone
        uow.session.add(user)
    await uow.session.flush()


class UserService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        async with UnitOfWork(self._sf) as uow:
            return await uow.users.get_by_telegram_id(telegram_id)

    async def get_by_phone(self, phone: str) -> Optional[User]:
        """Telefon orqali mijozni topadi — ISTALGAN (primary yoki qo'shimcha)
        raqami bo'yicha. Telefon normalize qilinmaydi — caller mas'ul (noto'g'ri
        format None qaytarsin, ValidationError emas)."""
        async with UnitOfWork(self._sf) as uow:
            return await uow.users.get_by_any_phone(phone)

    async def find_by_any_phone_raw(self, raw_phone: str) -> Optional[User]:
        """Operator lookup: xom kiritilgan raqamni normalize qilib izlaydi.
        Noto'g'ri format — None (xato emas)."""
        phone = normalize_phone_or_none(raw_phone)
        if phone is None:
            return None
        async with UnitOfWork(self._sf) as uow:
            return await uow.users.get_by_any_phone(phone)

    async def search_customers(self, q: str, *, limit: int = 8) -> Sequence[User]:
        """Operator qidiruvi — ism yoki istalgan telefon raqami bo'yicha."""
        async with UnitOfWork(self._sf) as uow:
            return await uow.users.search_name_or_phone(q, limit=limit)

    async def is_registered(self, telegram_id: int) -> bool:
        return (await self.get_by_telegram_id(telegram_id)) is not None

    async def mark_started_bot(self, telegram_id: int) -> None:
        """Mijoz botga /start bosganini belgilash — DM xabar yuborilishi uchun ruxsat."""
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get_by_telegram_id(telegram_id)
            if user is None or user.has_started_bot:
                return
            user.has_started_bot = True
            await uow.users.add(user)

    # ---------------------- Telefon raqamlar boshqaruvi ----------------------

    async def list_phones(self, user_id: int) -> Sequence[UserPhone]:
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise EntityNotFoundError("user_not_registered")
            return await uow.users.list_phone_rows(user_id)

    async def add_phone(
        self,
        user_id: int,
        raw_phone: str,
        *,
        label: str = "",
        make_primary: bool = False,
    ) -> UserPhone:
        """Mijozga yangi raqam biriktiradi.

        Qoidalar:
          * Raqam GLOBAL unique — boshqa mijozniki bo'lsa `phone_taken`
            (kontekstda egasi ID'si — operator UI "bu mijozga o'tish" ko'rsatadi).
          * Shu mijozda allaqachon bor — idempotent (mavjud qator qaytadi).
          * MAX_PHONES_PER_USER cap.
        """
        phone = _normalize_phone(raw_phone)
        label = (label or "").strip()[:40] or None
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise EntityNotFoundError("user_not_registered")

            existing_row = await uow.users.get_phone_row_by_number(phone)
            if existing_row is not None:
                if existing_row.user_id != user_id:
                    raise InvalidOperationError(
                        "phone_taken", context={"owner_user_id": existing_row.user_id},
                    )
                # Idempotent: bor raqam — faqat label/primary yangilanishi mumkin.
                if label and existing_row.label != label:
                    existing_row.label = label
                    uow.session.add(existing_row)
                if make_primary:
                    await _sync_primary_phone(uow, user, phone)
                await uow.session.flush()
                return existing_row

            # users.phone_number keshi ham global bo'shligini tekshiramiz
            # (backfill'gacha qolgan yozuvlar uchun himoya).
            owner = await uow.users.get_by_any_phone(phone)
            if owner is not None and owner.id != user_id:
                raise InvalidOperationError(
                    "phone_taken", context={"owner_user_id": owner.id},
                )

            if await uow.users.count_phones(user_id) >= MAX_PHONES_PER_USER:
                raise ValidationError(
                    "phone_limit_reached", context={"max": MAX_PHONES_PER_USER},
                )

            try:
                if make_primary:
                    await _sync_primary_phone(uow, user, phone)
                    row = await uow.users.get_phone_row_by_number(phone)
                    assert row is not None
                    if label:
                        row.label = label
                        uow.session.add(row)
                        await uow.session.flush()
                    return row

                row = UserPhone(user_id=user_id, phone=phone, is_primary=False, label=label)
                uow.session.add(row)
                await uow.session.flush()
                return row
            except IntegrityError:
                # Check-then-insert oynasidagi race: parallel so'rov shu raqamni
                # boshqa mijozga ulgurib qo'shgan — 500 emas, aniq phone_taken.
                raise InvalidOperationError("phone_taken")

    async def remove_phone(self, user_id: int, phone_id: int) -> None:
        """Raqamni o'chiradi. Primary raqam o'chirilmaydi — avval boshqasini
        primary qiling (aniq, oldindan aytiladigan qoida)."""
        async with UnitOfWork(self._sf) as uow:
            row = await uow.users.get_phone_row(phone_id)
            if row is None or row.user_id != user_id:
                raise EntityNotFoundError("phone_not_found")
            if row.is_primary:
                raise InvalidOperationError("phone_primary_undeletable")
            await uow.session.delete(row)
            await uow.session.flush()

    async def set_primary_phone(self, user_id: int, phone_id: int) -> UserPhone:
        """Raqamni primary qiladi — `users.phone_number` keshi sinxron yangilanadi."""
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise EntityNotFoundError("user_not_registered")
            row = await uow.users.get_phone_row(phone_id)
            if row is None or row.user_id != user_id:
                raise EntityNotFoundError("phone_not_found")
            await _sync_primary_phone(uow, user, row.phone)
            return row

    # ---------------------- Ro'yxatdan o'tish / operator oqimi ----------------------

    async def create_customer(
        self,
        *,
        full_name: str,
        phone_number: str,
        rename_existing: bool = True,
        initial_bottles: int = 0,
        operator_id: int | None = None,
    ) -> tuple[User, bool]:
        """Operator/admin qo'lda mijoz qo'shadi (yoki mavjudini topadi).

        Mantiq:
          1. Telefon orqali izlash (ISTALGAN raqami) — mavjud bo'lsa qaytarish
             (`created=False`; arxivda bo'lsa tiklanadi)
          2. Yo'q bo'lsa — sintetik manfiy `telegram_id` bilan yangi guest mijoz
             (`has_started_bot=False`, DM yuborilmaydi) — `created=True`

        `rename_existing` — mavjud mijoz ismini kiritilgan ismga yangilashmi:
          * True  — buyurtma oqimi (operator mijoz bilan gaplashib, joriy ismni
            tasdiqlagan; find_or_create_for_operator shu bilan chaqiradi)
          * False — "mijoz qo'shish" oqimi: telefon boshqa mijozniki bo'lsa,
            uning ismiga JIMGINA tegilmaydi (operator adashib boshqa odam
            raqamini kiritsa mavjud mijoz ma'lumoti buzilmasin)

        Mijoz keyinroq botga /start yuborib ro'yxatdan o'tsa, `register()` bu
        guest hisobni o'sha real `telegram_id` ga BIRIKTIRADI (identity merge):
        `user.id` saqlanadi, shuning uchun buyurtmalar/balanslar/ledger yo'qolmaydi.

        Returns: (user, created) — created=True yangi yaratilgan bo'lsa.
        """
        full_name = (full_name or "").strip()
        if len(full_name) < 2:
            raise ValidationError("name_too_short")
        phone = _normalize_phone(phone_number)

        async with UnitOfWork(self._sf) as uow:
            existing = await uow.users.get_by_any_phone(phone)
            if existing is not None:
                # Eski mijoz — arxivlangan bo'lsa qayta tiklaymiz (operator uni
                # ro'yxatda ko'rmaydi; qo'shish niyati = qayta ishlatish niyati)
                if existing.is_deleted:
                    await uow.users.restore(existing)
                # Ism yangilash — faqat buyurtma oqimida (rename_existing=True)
                if rename_existing and existing.full_name != full_name:
                    existing.full_name = full_name
                    await uow.users.add(existing)
                # Raqam user_phones'da yo'q bo'lsa (faqat keshda bor) — qator ochamiz.
                row = await uow.users.get_phone_row_by_number(phone)
                if row is None:
                    uow.session.add(UserPhone(
                        user_id=existing.id, phone=phone,
                        is_primary=(existing.phone_number == phone),
                    ))
                    await uow.session.flush()
                return existing, False

            # Yangi mijoz — sintetik manfiy telegram_id (vaqt asosida, unique+monotonik)
            synthetic_tg = -int(time.time_ns() // 1000)
            user = User(
                telegram_id=synthetic_tg,
                full_name=full_name,
                phone_number=phone,
                has_started_bot=False,  # bot bilan ishlamaydi, DM yuborilmaydi
            )
            user = await uow.users.add(user)
            uow.session.add(UserPhone(user_id=user.id, phone=phone, is_primary=True))
            await uow.session.flush()

            # Boshlang'ich idishlar — mijozda ALLAQACHON (tizim'gacha) yig'ilgan
            # idishlar. post_ledger orqali: balans keshi + jurnal invarianti
            # birga (BOTTLE_ADJUST). FAQAT yangi yaratilganda — mavjud mijoz
            # balansi bu oqimdan o'zgartirilmaydi (admin adjust alohida).
            # Qator shu tranzaksiyada yangi yaratilgan — unga boshqa sessiya
            # tegolmaydi, alohida lock shart emas.
            bottles0 = max(0, int(initial_bottles or 0))
            if bottles0 > 0:
                await post_ledger(
                    uow, subject=user,
                    account=LedgerAccount.BOTTLES, kind=LedgerKind.BOTTLE_ADJUST,
                    delta=bottles0, operator_id=operator_id,
                    reason="Boshlang'ich idishlar (mijoz qo'shilganda kiritildi)",
                )
            return user, True

    async def find_or_create_for_operator(
        self, *, full_name: str, phone_number: str,
    ) -> User:
        """Operator orderi uchun mijoz topish/yaratish — `create_customer` ustidan
        (buyurtma oqimi faqat user'ni kutadi, created flag kerak emas)."""
        user, _ = await self.create_customer(full_name=full_name, phone_number=phone_number)
        return user

    async def register(self, data: RegistrationInput) -> User:
        full_name = (data.full_name or "").strip()
        if len(full_name) < 2:
            raise ValidationError("name_too_short")
        phone = _normalize_phone(data.phone_number)

        async with UnitOfWork(self._sf) as uow:
            existing = await uow.users.get_by_telegram_id(data.telegram_id)
            if existing:
                # Telefon BOSHQA mijozga tegishli bo'lsa — o'g'irlab bo'lmaydi.
                owner = await uow.users.get_by_any_phone(phone)
                if owner is not None and owner.id != existing.id:
                    raise ValidationError("phone_taken")
                if existing.is_deleted:
                    await uow.users.restore(existing)
                existing.full_name = full_name
                existing.has_started_bot = True
                await uow.users.add(existing)
                await _sync_primary_phone(uow, existing, phone)
                return existing

            phone_owner = await uow.users.get_by_any_phone(phone)
            if phone_owner is not None:
                # IDENTITY MERGE — telefon allaqachon "guest" hisobga tegishli
                # (operator yaratgan, botga hali /start qilmagan). Uni shu real
                # Telegram hisobiga BIRIKTIRAMIZ (adopt): operator yaratgan
                # buyurtmalar, balanslar va ledger yozuvlari user.id ga
                # bog'langan — telegram_id ni o'zgartirsak ham saqlanadi.
                #
                # Faqat GUEST (has_started_bot=False) hisob biriktiriladi.
                # Telefon haqiqiy, faollashgan boshqa hisobga tegishli bo'lsa —
                # uni o'g'irlab bo'lmaydi (himoya: phone_taken).
                if not phone_owner.has_started_bot:
                    if phone_owner.is_deleted:
                        await uow.users.restore(phone_owner)
                    old_tg = phone_owner.telegram_id
                    phone_owner.telegram_id = data.telegram_id
                    phone_owner.full_name = full_name
                    phone_owner.has_started_bot = True
                    await uow.users.add(phone_owner)
                    await _sync_primary_phone(uow, phone_owner, phone)
                    log.info(
                        "Identity merge: guest user id=%s (tg %s -> %s) phone=%s adopted",
                        phone_owner.id, old_tg, data.telegram_id, phone,
                    )
                    return phone_owner
                raise ValidationError("phone_taken")

            user = User(
                telegram_id=data.telegram_id,
                full_name=full_name,
                phone_number=phone,
                has_started_bot=True,
            )
            user = await uow.users.add(user)
            uow.session.add(UserPhone(user_id=user.id, phone=phone, is_primary=True))
            await uow.session.flush()
            return user

    async def archive(self, user_id: int) -> None:
        """SOFT DELETE — mijozni arxivlash. Eski buyurtmalar admin uchun saqlanadi.
        Mijoz qaytadan /start yuborsa — avtomatik tiklanadi (register orqali).
        Idempotent.
        """
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get(user_id)
            if user is None or user.is_deleted:
                return
            await uow.users.soft_delete(user)

    async def restore(self, user_id: int) -> User:
        """Arxivdan qaytaradi (admin manual)."""
        async with UnitOfWork(self._sf) as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise EntityNotFoundError("user_not_registered")
            if not user.is_deleted:
                return user
            return await uow.users.restore(user)
