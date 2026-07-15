"""Telefon normalizatsiyasi testlari — `python -m unittest discover tests`.

Service/phone.py — butun tizimning identity kaliti; qoidalar o'zgartirilsa
bu testlar birinchi bo'lib sindiradi (JS ko'zgusini ham yangilashni unutmang).
"""
import unittest

from Service.exceptions import ValidationError
from Service.phone import (
    normalize_phone,
    normalize_phone_lenient,
    normalize_phone_or_none,
)


class NormalizePhoneTest(unittest.TestCase):
    def test_local_9_digits_gets_998(self):
        self.assertEqual(normalize_phone("901234567"), "+998901234567")

    def test_998_prefix_without_plus(self):
        self.assertEqual(normalize_phone("998901234567"), "+998901234567")

    def test_full_e164_kept(self):
        self.assertEqual(normalize_phone("+998901234567"), "+998901234567")

    def test_separators_stripped(self):
        self.assertEqual(normalize_phone("+998 90 123-45-67"), "+998901234567")
        self.assertEqual(normalize_phone("(90) 123 45 67"), "+998901234567")

    def test_legacy_8_prefix(self):
        self.assertEqual(normalize_phone("8998901234567"), "+998901234567")

    def test_foreign_international_kept(self):
        self.assertEqual(normalize_phone("+15551234567"), "+15551234567")

    def test_invalid_raises(self):
        for bad in ("", "   ", "abc", "12345", "+12"):
            with self.assertRaises(ValidationError, msg=bad):
                normalize_phone(bad)

    def test_bare_10_digits_without_plus_invalid(self):
        # Eski kod '+' qo'shib '+9012345678' kabi hech qachon mos kelmaydigan
        # "yarim" raqam yaratardi — endi aniq invalid.
        with self.assertRaises(ValidationError):
            normalize_phone("9012345678")

    def test_or_none(self):
        self.assertIsNone(normalize_phone_or_none(None))
        self.assertIsNone(normalize_phone_or_none(""))
        self.assertIsNone(normalize_phone_or_none("abc"))
        self.assertEqual(normalize_phone_or_none("901234567"), "+998901234567")

    def test_lenient_falls_back_to_raw(self):
        self.assertEqual(normalize_phone_lenient("901234567"), "+998901234567")
        # Tushunarsiz format — kesilgan xom matn (contact_phone identity emas)
        self.assertEqual(normalize_phone_lenient("ichki 12"), "ichki 12")
        self.assertEqual(normalize_phone_lenient(None), "")


if __name__ == "__main__":
    unittest.main()
