"""Promouter (uyma-uy ishchilar) — promokod va atributsiya testlari.

Eng muhim qism: `ResolveOrderAttributionTest` — promouter ishdan ketganda yoki
bonus davri tugaganda `orders` jadvalida MUAMMO BO'LMASLIGI kerak. Kutilgan
xulq: atributsiya (kim olib kelgan) SAQLANADI, faqat bonus 0 ga tushadi.
"""
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from Service.exceptions import ValidationError
from Service.promo_code import (
    generate_promo_code,
    normalize_promo_code,
    normalize_promo_code_lenient,
)
from Service.promoter_service import resolve_order_attribution


class NormalizePromoCodeTest(unittest.TestCase):
    def test_uppercase_and_separators_stripped(self):
        for raw in ("ab-12cd", "AB 12 CD", " ab12cd ", "ab_12.cd", "(ab)12cd"):
            self.assertEqual(normalize_promo_code_lenient(raw), "AB12CD", raw)

    def test_admin_may_use_meaningful_codes(self):
        """O/0/I/1 faqat GENERATSIYADA chiqarilgan — admin qo'lda bera oladi."""
        self.assertEqual(normalize_promo_code("OLIM01"), "OLIM01")
        self.assertEqual(normalize_promo_code_lenient("ali1"), "ALI1")

    def test_lenient_returns_empty_on_bad_input(self):
        # Mijozga "format xato" va "topilmadi" ajratilmaydi — ikkalasi ham "".
        for raw in ("", None, "AB", "A" * 17, "AB!@", "АБВГ"):
            self.assertEqual(normalize_promo_code_lenient(raw), "", repr(raw))

    def test_strict_raises_specific_codes(self):
        for raw, expected in [
            ("", "promo_code_required"),
            ("AB", "promoter_code_length"),
            ("A" * 17, "promoter_code_length"),
            ("AB!@", "promoter_code_charset"),
        ]:
            with self.assertRaises(ValidationError) as cm:
                normalize_promo_code(raw)
            self.assertEqual(cm.exception.code, expected, repr(raw))


class GeneratePromoCodeTest(unittest.TestCase):
    def test_avoids_confusing_characters(self):
        """Avtomatik kod og'zaki aytiladi — O↔0, I↔1↔L bo'lmasligi shart."""
        for _ in range(200):
            code = generate_promo_code()
            self.assertFalse(set(code) & set("OI01L"), f"chalkash belgi: {code}")

    def test_generated_codes_pass_validation(self):
        for _ in range(50):
            code = generate_promo_code()
            self.assertEqual(normalize_promo_code_lenient(code), code)


# ---------------- resolve_order_attribution uchun soxta (fake) UoW ----------------


@dataclass
class _FakePromoter:
    id: int = 7
    promo_code: str = "ABCD23"
    is_active: bool = True
    deleted_at: Optional[datetime] = None


@dataclass
class _FakeRedemption:
    promoter_id: int
    promo_code: str
    bonus_window_ends_at: datetime


@dataclass
class _FakeSettings:
    promoter_program_enabled: bool = True
    promoter_bonus_per_order: Decimal = Decimal("5000")
    promoter_bonus_window_days: int = 90


class _FakeUoW:
    """`resolve_order_attribution` faqat shu uch repoga murojaat qiladi."""

    def __init__(self, redemption, promoter, settings):
        outer = self
        self._redemption, self._promoter, self._settings = redemption, promoter, settings

        class _Redemptions:
            async def get_by_customer(self, customer_id):
                return outer._redemption

        class _Promoters:
            async def get(self, promoter_id):
                return outer._promoter

        class _Settings:
            async def get_or_create(self):
                return outer._settings

        self.promoter_redemptions = _Redemptions()
        self.promoters = _Promoters()
        self.settings = _Settings()


def _uow(*, redemption=..., promoter=..., settings=..., days_left=30):
    """Soxta UoW quradi.

    Sentinel `...` (None EMAS): `promoter=None` va `redemption=None` — bular
    haqiqiy sinov holatlari ("qator yo'q"), shuning uchun ular "standart
    qiymatni ishlat" degani bo'lib qolmasligi kerak.
    """
    if redemption is ...:
        redemption = _FakeRedemption(
            promoter_id=7, promo_code="ABCD23",
            bonus_window_ends_at=datetime.now(timezone.utc) + timedelta(days=days_left),
        )
    if promoter is ...:
        promoter = _FakePromoter()
    if settings is ...:
        settings = _FakeSettings()
    return _FakeUoW(redemption, promoter, settings)


class ResolveOrderAttributionTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_redemption_gives_nothing(self):
        pid, code, bonus = await resolve_order_attribution(_uow(redemption=None), 1)
        self.assertIsNone(pid)
        self.assertEqual(code, "")
        self.assertEqual(bonus, Decimal("0.00"))

    async def test_happy_path_stamps_id_code_and_bonus(self):
        pid, code, bonus = await resolve_order_attribution(_uow(), 1)
        self.assertEqual((pid, code), (7, "ABCD23"))
        self.assertEqual(bonus, Decimal("5000.00"))

    # ---- Egasi aynan so'ragan holatlar: muammo bo'lmasligi kerak ----

    async def test_expired_window_keeps_attribution_drops_bonus(self):
        """Bonus davri tugagan: kim olib kelgani SAQLANADI, puli 0."""
        pid, code, bonus = await resolve_order_attribution(_uow(days_left=-1), 1)
        self.assertEqual((pid, code), (7, "ABCD23"), "atributsiya yo'qolmasligi kerak")
        self.assertEqual(bonus, Decimal("0.00"))

    async def test_inactive_promoter_keeps_attribution_drops_bonus(self):
        """Ishchi to'xtatilgan: atributsiya saqlanadi, puli 0."""
        pid, code, bonus = await resolve_order_attribution(
            _uow(promoter=_FakePromoter(is_active=False)), 1,
        )
        self.assertEqual((pid, code), (7, "ABCD23"))
        self.assertEqual(bonus, Decimal("0.00"))

    async def test_archived_promoter_keeps_attribution_drops_bonus(self):
        """Ishchi ishdan ketgan (arxivlangan): atributsiya saqlanadi, puli 0."""
        pid, code, bonus = await resolve_order_attribution(
            _uow(promoter=_FakePromoter(deleted_at=datetime.now(timezone.utc))), 1,
        )
        self.assertEqual((pid, code), (7, "ABCD23"))
        self.assertEqual(bonus, Decimal("0.00"))

    async def test_hard_deleted_promoter_row_does_not_crash(self):
        """Promouter qatori umuman yo'q (purge): yiqilmaydi, kod snapshot qoladi."""
        pid, code, bonus = await resolve_order_attribution(_uow(promoter=None), 1)
        self.assertEqual((pid, code), (7, "ABCD23"))
        self.assertEqual(bonus, Decimal("0.00"))

    # ---- Sozlamalar ----

    async def test_disabled_program_drops_bonus(self):
        pid, _, bonus = await resolve_order_attribution(
            _uow(settings=_FakeSettings(promoter_program_enabled=False)), 1,
        )
        self.assertEqual(pid, 7)
        self.assertEqual(bonus, Decimal("0.00"))

    async def test_zero_configured_bonus(self):
        _, _, bonus = await resolve_order_attribution(
            _uow(settings=_FakeSettings(promoter_bonus_per_order=Decimal("0"))), 1,
        )
        self.assertEqual(bonus, Decimal("0.00"))

    async def test_naive_window_datetime_does_not_crash(self):
        """DB'dan tz-siz sana kelsa — UTC deb qaraladi, TypeError bermaydi."""
        naive = (datetime.now(timezone.utc) + timedelta(days=5)).replace(tzinfo=None)
        red = _FakeRedemption(
            promoter_id=7, promo_code="ABCD23", bonus_window_ends_at=naive,
        )
        pid, _, bonus = await resolve_order_attribution(_uow(redemption=red), 1)
        self.assertEqual(pid, 7)
        self.assertEqual(bonus, Decimal("5000.00"))

    async def test_bonus_is_quantized_to_two_places(self):
        _, _, bonus = await resolve_order_attribution(
            _uow(settings=_FakeSettings(promoter_bonus_per_order=Decimal("1234.5"))), 1,
        )
        self.assertEqual(bonus, Decimal("1234.50"))
        self.assertEqual(bonus.as_tuple().exponent, -2)


if __name__ == "__main__":
    unittest.main()
