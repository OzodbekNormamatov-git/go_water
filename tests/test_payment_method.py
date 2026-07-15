"""PaymentMethod enum testlari."""
import unittest

from Domain.enums import PaymentMethod


class PaymentMethodTest(unittest.TestCase):
    def test_parse_values(self):
        self.assertIs(PaymentMethod.parse("cash"), PaymentMethod.CASH)
        self.assertIs(PaymentMethod.parse("card"), PaymentMethod.CARD)
        self.assertIs(PaymentMethod.parse("deposit"), PaymentMethod.DEPOSIT)

    def test_parse_case_and_spaces(self):
        self.assertIs(PaymentMethod.parse(" CASH "), PaymentMethod.CASH)

    def test_empty_defaults_cash(self):
        self.assertIs(PaymentMethod.parse(None), PaymentMethod.CASH)
        self.assertIs(PaymentMethod.parse(""), PaymentMethod.CASH)

    def test_unknown_raises(self):
        with self.assertRaises(ValueError):
            PaymentMethod.parse("bitcoin")

    def test_labels(self):
        self.assertEqual(PaymentMethod.CASH.label_uz, "Naqd")
        self.assertEqual(PaymentMethod.DEPOSIT.emoji, "💰")


if __name__ == "__main__":
    unittest.main()
