"""Rasxod davr matematikasi testlari — sof funksiyalar.

Qamrov: doimiy rasxod sanalari generatsiyasi (occurrences_between),
qamrov davri validatsiyasi va yillik davr oxiri hisoblash.
"""
import unittest
from datetime import date

from Domain.models.expense import ExpensePeriod
from Service.exceptions import ValidationError
from Service.expense_service import (
    _add_year_minus_day,
    _validate_period_range,
    clamp_day_to_month,
    occurrences_between,
)


class ClampDayTest(unittest.TestCase):
    def test_clamps_to_month_end(self):
        self.assertEqual(clamp_day_to_month(2026, 2, 31), date(2026, 2, 28))
        self.assertEqual(clamp_day_to_month(2028, 2, 31), date(2028, 2, 29))  # kabisa
        self.assertEqual(clamp_day_to_month(2026, 7, 15), date(2026, 7, 15))


class OccurrencesTest(unittest.TestCase):
    def test_monthly(self):
        occs = occurrences_between(
            ExpensePeriod.MONTHLY, 1, None, date(2026, 1, 1), date(2026, 3, 31),
        )
        self.assertEqual(occs, [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)])

    def test_yearly_single_occurrence(self):
        occs = occurrences_between(
            ExpensePeriod.YEARLY, 15, 6, date(2026, 1, 1), date(2026, 12, 31),
        )
        self.assertEqual(occs, [date(2026, 6, 15)])

    def test_weekly(self):
        # 2026-07-06 — dushanba (weekday 0)
        occs = occurrences_between(
            ExpensePeriod.WEEKLY, 0, None, date(2026, 7, 1), date(2026, 7, 20),
        )
        self.assertEqual(occs, [date(2026, 7, 6), date(2026, 7, 13), date(2026, 7, 20)])

    def test_empty_when_range_inverted(self):
        self.assertEqual(
            occurrences_between(
                ExpensePeriod.MONTHLY, 1, None, date(2026, 5, 1), date(2026, 4, 1),
            ),
            [],
        )


class PeriodRangeTest(unittest.TestCase):
    def test_both_none_ok(self):
        _validate_period_range(None, None)  # xato yo'q

    def test_valid_pair_ok(self):
        _validate_period_range(date(2026, 7, 1), date(2027, 6, 30))

    def test_half_pair_rejected(self):
        with self.assertRaises(ValidationError):
            _validate_period_range(date(2026, 7, 1), None)
        with self.assertRaises(ValidationError):
            _validate_period_range(None, date(2026, 7, 1))

    def test_inverted_rejected(self):
        with self.assertRaises(ValidationError):
            _validate_period_range(date(2026, 7, 2), date(2026, 7, 1))

    def test_over_5_years_rejected(self):
        with self.assertRaises(ValidationError):
            _validate_period_range(date(2026, 1, 1), date(2062, 1, 1))


class AddYearTest(unittest.TestCase):
    def test_regular(self):
        self.assertEqual(_add_year_minus_day(date(2026, 6, 15)), date(2027, 6, 14))

    def test_leap_day(self):
        self.assertEqual(_add_year_minus_day(date(2028, 2, 29)), date(2029, 2, 27))


if __name__ == "__main__":
    unittest.main()
